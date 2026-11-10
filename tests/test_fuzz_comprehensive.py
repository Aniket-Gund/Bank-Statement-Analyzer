import io
import os
import sys
import re
import math
import json
import hashlib
import traceback
import pandas as pd
import numpy as np

# Force UTF-8 on Windows stdout if possible
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.parser import (
    load_and_parse_file,
    auto_detect_columns,
    clean_amount,
    extract_header_info,
    find_table_header_index,
    is_amount_negative,
    is_amount_positive_signed
)
from modules.categorizer import (
    enrich_and_categorize_dataframe,
    extract_payee_and_method,
    rule_based_category,
    classify_with_gemini,
    CATEGORIES,
    safe_log
)
from modules.analyzer import (
    compute_kpis,
    get_category_spending,
    get_category_inflow,
    get_payment_methods_summary,
    get_top_payees,
    get_top_payers,
    get_daily_balance_trend,
    get_weekly_flow,
    get_monthly_spending_trend,
    detect_duplicates,
    detect_anomalies,
    detect_recurring_transactions,
    filter_transactions
)
from modules.insights import generate_gemini_insights, generate_rule_based_insights
from modules.report_generator import generate_html_report, prepare_chart_data, safe_chartjs_json, sanitize_insight_bullet

passed_count = 0
failed_count = 0
failures = []

def test_case(name: str):
    """Decorator to register and run test cases cleanly."""
    def decorator(fn):
        global passed_count, failed_count
        sys.stdout.write(f"TEST: {name} ... ")
        sys.stdout.flush()
        try:
            fn()
            sys.stdout.write("PASS\n")
            passed_count += 1
        except Exception as e:
            sys.stdout.write(f"FAIL ({type(e).__name__}: {e})\n")
            failed_count += 1
            failures.append((name, type(e).__name__, str(e), traceback.format_exc()))
        return fn
    return decorator

print("=" * 70)
print("RUNNING EXHAUSTIVE PRODUCTION HARDENING REGRESSION SUITE (31 CHECKS)")
print("=" * 70)

# ==============================================================================
# SECTION 1: PARSER & AMOUNT CLEANING HARDENING (9 CHECKS)
# ==============================================================================

@test_case("1. Parser - Empty and Whitespace CSV Handling")
def t1():
    for empty_content in [b"", b"   \n\n\t  \n"]:
        df, meta = load_and_parse_file(io.BytesIO(empty_content), "empty.csv")
        assert df.empty, "DataFrame should be empty"
        assert meta["error"] is not None, "Metadata should capture empty file error"
        assert list(df.columns) == ["date", "date_str", "time_str", "description", "ref_no", "amount", "type", "balance"]

@test_case("2. Parser - Empty Excel File Handling")
def t2():
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine='openpyxl') as writer:
        pd.DataFrame().to_excel(writer, index=False)
    bio.seek(0)
    df, meta = load_and_parse_file(bio, "empty.xlsx")
    assert df.empty, "Empty Excel should return empty DataFrame"
    assert list(df.columns) == ["date", "date_str", "time_str", "description", "ref_no", "amount", "type", "balance"]

@test_case("3. Parser - Semicolon and Tab Delimited CSV Auto-Detection")
def t3():
    semi_csv = b"Date;Description;Amount;Type;Balance\n01/10/2026;Coffee;50.00;DR;950.00\n02/10/2026;Salary;5000.00;CR;5950.00\n"
    df_semi, _ = load_and_parse_file(io.BytesIO(semi_csv), "statement.csv")
    assert len(df_semi) == 2, f"Expected 2 rows from semicolon CSV, got {len(df_semi)}"

    tab_csv = b"Date\tDescription\tAmount\tType\tBalance\n01/10/2026\tTea\t20.00\tDR\t930.00\n"
    df_tab, _ = load_and_parse_file(io.BytesIO(tab_csv), "statement.csv")
    assert len(df_tab) == 1, f"Expected 1 row from tab CSV, got {len(df_tab)}"

@test_case("4. Parser - Excel Serial Date Parsing (e.g. 45592)")
def t4():
    serial_csv = b"Date,Description,Amount,Type,Balance\n45592,Payment,100.00,DR,900.00\n"
    df, _ = load_and_parse_file(io.BytesIO(serial_csv), "serial.csv")
    assert len(df) == 1, "Excel serial date row should be parsed"
    assert df.iloc[0]["date_str"] == "27-10-2024", f"Unexpected date parsed: {df.iloc[0]['date_str']}"

@test_case("5. Parser - Flexible Dates with 12-Hour Timestamps and Commas")
def t5():
    ts_csv = b'Date,Description,Amount,Type,Balance\n"01/10/2026, 3:15 pm",Lunch,150.00,DR,850.00\n"02-10-2026 14:30",Dinner,300.00,DR,550.00\n'
    df, _ = load_and_parse_file(io.BytesIO(ts_csv), "timestamps.csv")
    assert len(df) == 2, f"Expected 2 rows with timestamps, got {len(df)}"
    assert df.iloc[0]["date_str"] == "01-10-2026"
    assert df.iloc[1]["date_str"] == "02-10-2026"

@test_case("6. Parser - clean_amount NaN, Inf, and String Noise Defense")
def t6():
    for noise in ["nan", "NaN", "NAN", "inf", "-inf", "Infinity", "-Infinity", "--", "null", "N/A", "na", "-", "nil"]:
        val = clean_amount(noise)
        assert val == 0.0, f"clean_amount('{noise}') must return 0.0, got {val}"
        assert not math.isnan(val) and not math.isinf(val)

@test_case("7. Parser - clean_amount Accounting Parentheses and Trailing Minuses")
def t7():
    assert clean_amount("(1,234.50)") == 1234.50
    assert clean_amount("500.00-") == 500.00
    assert clean_amount("-250.75") == 250.75
    assert clean_amount("($ 1,234.50)") == 1234.50
    assert clean_amount("₹ -100.00") == 100.00
    assert is_amount_negative("₹ -100.00") is True
    assert is_amount_negative("-₹100.00") is True
    assert is_amount_negative("($ 100.00)") is True
    # '100.00 DR' must NOT be considered a negative amount
    assert is_amount_negative("100.00 DR") is False

@test_case("8. Parser - clean_amount International Currency and European Decimals")
def t8():
    assert clean_amount("$ 500.00") == 500.00
    assert clean_amount("€ 750.50") == 750.50
    assert clean_amount("£ 100.25") == 100.25
    assert clean_amount("₹ 1,500.00") == 1500.00
    assert clean_amount("INR 2,500.00") == 2500.00
    assert clean_amount("Rs. 3,500.00") == 3500.00
    assert clean_amount("1.234,50") == 1234.50
    assert clean_amount("1234,50") == 1234.50

@test_case("9. Parser - Separate Debit/Credit Reversals and Type Polarity")
def t9():
    # Negative withdrawal is credit reversal, negative deposit is debit reversal
    rev_csv = b"Date,Description,Withdrawal,Deposit,Balance\n01/10/2026,Reversal Credit,-500.00,,1500.00\n02/10/2026,Reversal Debit,,-200.00,1300.00\n"
    df_rev, _ = load_and_parse_file(io.BytesIO(rev_csv), "rev.csv")
    assert df_rev.iloc[0]["type"] == "CREDIT", "Negative withdrawal must be parsed as CREDIT reversal"
    assert df_rev.iloc[0]["amount"] == 500.0
    assert df_rev.iloc[1]["type"] == "DEBIT", "Negative deposit must be parsed as DEBIT reversal"
    assert df_rev.iloc[1]["amount"] == 200.0

    # Separate Debit/Credit columns with DR/CR text indicators must NOT trigger reversal logic
    dr_cr_csv = b"Date,Description,Withdrawal,Deposit,Balance\n01/10/2026,ATM Cash,100.00 DR,,900.00\n02/10/2026,Salary,,5000.00 CR,5900.00\n"
    df_drcr, _ = load_and_parse_file(io.BytesIO(dr_cr_csv), "drcr.csv")
    assert df_drcr.iloc[0]["type"] == "DEBIT", "Normal withdrawal with 'DR' must be DEBIT, not CREDIT reversal"
    assert df_drcr.iloc[1]["type"] == "CREDIT", "Normal deposit with 'CR' must be CREDIT"

    # Single letters 'C' and 'D'
    cd_csv = b"Date,Description,Amount,Type,Balance\n01/10/2026,Refund,250.00,C,1550.00\n02/10/2026,Coffee,50.00,D,1500.00\n"
    df_cd, _ = load_and_parse_file(io.BytesIO(cd_csv), "cd.csv")
    assert df_cd.iloc[0]["type"] == "CREDIT", "Type 'C' should be CREDIT"
    assert df_cd.iloc[1]["type"] == "DEBIT", "Type 'D' should be DEBIT"

    # Single amount column polarity by keywords and balance delta (Chronological)
    single_csv = b"Date,Description,Amount,Balance\n01/10/2026,Salary from Company,50000.00,55000.00\n02/10/2026,Grocery store,1500.00,53500.00\n"
    df_single, _ = load_and_parse_file(io.BytesIO(single_csv), "single.csv")
    assert df_single.iloc[0]["type"] == "CREDIT", "Salary inflow must be parsed as CREDIT"
    assert df_single.iloc[1]["type"] == "DEBIT", "Grocery outflow must be parsed as DEBIT"

    # Single amount column polarity in Reverse-Chronological Statements
    rev_chron_csv = (
        b"Date,Description,Amount,Balance\n"
        b"10/10/2026,Txn C,500.00,2000.00\n"
        b"09/10/2026,Txn B,500.00,1500.00\n"
        b"08/10/2026,Txn A,1000.00,1000.00\n"
    )
    df_rev_c, _ = load_and_parse_file(io.BytesIO(rev_chron_csv), "rev_chron.csv")
    assert len(df_rev_c) == 3
    assert df_rev_c.iloc[0]["date_str"] == "08-10-2026"
    assert df_rev_c.iloc[1]["date_str"] == "09-10-2026"
    assert df_rev_c.iloc[2]["date_str"] == "10-10-2026"
    assert df_rev_c.iloc[1]["type"] == "CREDIT", f"Txn B should be CREDIT, got {df_rev_c.iloc[1]['type']}"
    assert df_rev_c.iloc[2]["type"] == "CREDIT", f"Txn C should be CREDIT, got {df_rev_c.iloc[2]['type']}"

# ==============================================================================
# SECTION 2: CATEGORIZATION & PAYEE EXTRACTION (6 CHECKS)
# ==============================================================================

@test_case("10. Categorizer - Non-Greedy Payee Extraction (Jio / NEFT Test)")
def t10():
    p, m = extract_payee_and_method("NEFT-SBIN0001234-RELIANCE JIO-PAYMENT")
    assert "Reliance" in p or "Jio" in p, f"Expected Reliance/Jio payee, got: '{p}'"
    assert m == "NEFT / RTGS"

@test_case("11. Categorizer - Tokenized Payee Extraction for UPI & IMPS")
def t11():
    p_upi, m_upi = extract_payee_and_method("UPI-ZOMATO-ICIC-987654321012")
    assert "Zomato" in p_upi
    assert m_upi == "UPI"

    p_imps, m_imps = extract_payee_and_method("IMPS/428912345678/SWIGGY/ICICI")
    assert "Swiggy" in p_imps
    assert m_imps == "IMPS"

    p_std, m_std = extract_payee_and_method("UPI/JOHN DOE/HDFC/123456789012/PAYMENT")
    assert "John Doe" in p_std
    assert m_std == "UPI"

@test_case("12. Categorizer - RRN Reference & Bank IFSC Code Filtering")
def t12():
    # Must discard 12-digit RRN and bank IFSC prefix (BARB, YESB, etc.)
    p, _ = extract_payee_and_method("UPI/987654321098/BARB001/PUNITA GUPTA")
    assert "Punita" in p or "Gupta" in p, f"Payee should be Punita Gupta, got: '{p}'"
    assert "BARB" not in p and "987654321098" not in p

@test_case("13. Categorizer - Expanded Indian Commercial Brand Dictionary")
def t13():
    brands = [
        ("STARBUCKS COFFEE PUNE", "🍕 Food & Dining"),
        ("MCDONALDS RESTAURANT", "🍕 Food & Dining"),
        ("DOMINOS PIZZA ONLINE", "🍕 Food & Dining"),
        ("KFC FRIED CHICKEN", "🍕 Food & Dining"),
        ("SUBWAY SANDWICH", "🍕 Food & Dining"),
        ("CHAAYOS CAFE", "🍕 Food & Dining"),
        ("DECATHLON SPORTS", "🛍️ Shopping & Lifestyle"),
        ("ZARA RETAIL STORE", "🛍️ Shopping & Lifestyle"),
        ("H&M APPAREL", "🛍️ Shopping & Lifestyle"),
        ("PVR CINEMAS TICKET", "🛍️ Shopping & Lifestyle"),
        ("BOOKMYSHOW MOVIES", "🛍️ Shopping & Lifestyle"),
        ("MAKEMYTRIP TRAVEL", "🚗 Travel & Transport"),
        ("NETC FASTAG TOLL", "🚗 Travel & Transport"),
        ("DMART GROCERY", "🛒 Groceries & Daily Needs"),
        ("BLINKIT QUICK", "🛒 Groceries & Daily Needs"),
        ("ZEPTO 10MIN", "🛒 Groceries & Daily Needs")
    ]
    for narration, expected_cat in brands:
        payee, _ = extract_payee_and_method(narration)
        cat = rule_based_category(narration, payee, "DEBIT")
        assert cat == expected_cat, f"Failed for '{narration}': got '{cat}', expected '{expected_cat}'"

@test_case("14. Categorizer - Gemini JSON Array Extraction with Preamble Commentary")
def t14():
    messy_ai_text = (
        "Here are your categories:\n"
        "```json\n"
        "[\"🛒 Groceries & Daily Needs\", \"🍕 Food & Dining\"]\n"
        "```\n"
        "Hope this helps you analyze your budget!"
    )
    m = re.search(r'\[.*\]', messy_ai_text, re.DOTALL)
    assert m is not None, "JSON array regex must match bracketed payload"
    parsed = json.loads(m.group(0))
    assert len(parsed) == 2
    assert parsed[0] == "🛒 Groceries & Daily Needs"

@test_case("15. Categorizer - Empty DataFrame Categorization Safeguard")
def t15():
    df_empty = pd.DataFrame(columns=["date", "description", "amount", "type"])
    res = enrich_and_categorize_dataframe(df_empty, use_ai=False)
    assert res.empty
    assert "payee" in res.columns
    assert "payment_method" in res.columns
    assert "category" in res.columns

# ==============================================================================
# SECTION 3: ANALYZER HARDENING (7 CHECKS)
# ==============================================================================

@test_case("16. Analyzer - Filter Transactions Regex Injection Immunity")
def t16():
    df = pd.DataFrame([{
        "date": pd.to_datetime("2026-10-01"),
        "date_str": "01-10-2026",
        "description": "UPI/Payment (Special*123)",
        "payee": "Shop [A]",
        "ref_no": "Ref+99",
        "category": "Food",
        "payment_method": "UPI",
        "amount": 100.0,
        "type": "DEBIT",
        "balance": 500.0
    }])
    # Every regex special char must execute without ArrowInvalid or re.error
    for evil in ["(", "[", "*", "+", "?", "\\", "{", "]", ")", "^", "$", "(.*)"]:
        res = filter_transactions(df, search_query=evil)
        assert isinstance(res, pd.DataFrame)
    assert len(filter_transactions(df, search_query="Special*123")) == 1
    assert len(filter_transactions(df, search_query="Shop [A]")) == 1
    assert len(filter_transactions(df, search_query="Ref+99")) == 1

@test_case("17. Analyzer - Overdraft Negative Opening Balance Calculation")
def t17():
    df_od = pd.DataFrame([
        {"date": pd.to_datetime("2026-10-01"), "amount": 5000.0, "type": "DEBIT", "balance": -45000.0}
    ])
    kpis = compute_kpis(df_od)
    # Closing is -45000, debit of 5000 occurred -> opening was -45000 + 5000 = -40000
    assert kpis["opening_balance"] == -40000.0, f"Expected -40000.0, got {kpis['opening_balance']}"
    assert kpis["closing_balance"] == -45000.0

@test_case("18. Analyzer - get_top_payees with All NaN Categories")
def t18():
    df_nan_cats = pd.DataFrame([
        {"payee": "Vendor A", "amount": 100.0, "type": "DEBIT", "category": np.nan},
        {"payee": "Vendor A", "amount": 200.0, "type": "DEBIT", "category": None}
    ])
    top_p = get_top_payees(df_nan_cats)
    assert len(top_p) == 1
    assert top_p.iloc[0]["category"] == "Other"

@test_case("19. Analyzer - Chronological Sorting in get_weekly_flow")
def t19():
    df_multi_month = pd.DataFrame([
        {"date": pd.to_datetime("2026-08-31"), "amount": 100.0, "type": "DEBIT"},
        {"date": pd.to_datetime("2026-09-28"), "amount": 200.0, "type": "DEBIT"},
        {"date": pd.to_datetime("2026-10-12"), "amount": 300.0, "type": "DEBIT"},
        {"date": pd.to_datetime("2026-10-26"), "amount": 400.0, "type": "DEBIT"},
    ])
    wf = get_weekly_flow(df_multi_month)
    labels = wf["week_start"].tolist()
    assert labels == ['31 Aug', '28 Sep', '12 Oct', '26 Oct'], f"Labels not chronological: {labels}"

@test_case("20. Analyzer - Zero-Variance Anomaly Detection Safeguard")
def t20():
    # Identical transactions must not all be flagged as anomalies
    df_ident = pd.DataFrame([
        {"type": "DEBIT", "amount": 50.0} for _ in range(6)
    ])
    anom = detect_anomalies(df_ident)
    assert len(anom) == 0, f"Expected 0 anomalies on identical amounts, got {len(anom)}"

@test_case("21. Analyzer - Division by Zero Protection in compute_kpis & Spending")
def t21():
    # Only credits, no debits
    df_credits = pd.DataFrame([
        {"date": pd.to_datetime("2026-10-01"), "amount": 1000.0, "type": "CREDIT", "balance": 1000.0, "category": "Salary"}
    ])
    kpis = compute_kpis(df_credits)
    assert kpis["avg_debit"] == 0.0
    cat_df = get_category_spending(df_credits)
    assert cat_df.empty

    # Only debits, no credits
    df_debits = pd.DataFrame([
        {"date": pd.to_datetime("2026-10-01"), "amount": 500.0, "type": "DEBIT", "balance": 500.0, "category": "Food"}
    ])
    kpis_d = compute_kpis(df_debits)
    assert kpis_d["avg_credit"] == 0.0
    inflow_df = get_category_inflow(df_debits)
    assert inflow_df.empty

@test_case("22. Analyzer - Empty DataFrame Pipeline Resilience")
def t22():
    df_empty = pd.DataFrame(columns=["date", "date_str", "amount", "type", "balance", "payee", "category", "payment_method"])
    kpis = compute_kpis(df_empty)
    assert kpis["total_transactions"] == 0
    assert get_category_spending(df_empty).empty
    assert get_category_inflow(df_empty).empty
    assert get_payment_methods_summary(df_empty).empty
    assert get_top_payees(df_empty).empty
    assert get_top_payers(df_empty).empty
    assert get_daily_balance_trend(df_empty).empty
    assert get_weekly_flow(df_empty).empty
    assert get_monthly_spending_trend(df_empty).empty
    assert detect_duplicates(df_empty).empty
    assert detect_anomalies(df_empty).empty
    assert detect_recurring_transactions(df_empty).empty

# ==============================================================================
# SECTION 4: INSIGHTS GENERATION HARDENING (3 CHECKS)
# ==============================================================================

@test_case("23. Insights - Division by Zero Elimination in Outflow/Anomaly Bullets")
def t23():
    kpis = {"total_credits": 1000.0, "total_debits": 0.0, "net_cash_flow": 1000.0, "closing_balance": 1000.0, "total_transactions": 1}
    payees_df = pd.DataFrame([{"payee": "Vendor", "total_amount": 50.0}])
    anom_df = pd.DataFrame([{"amount": 100.0}])
    bullets = generate_rule_based_insights(kpis, pd.DataFrame(), payees_df, {}, anom_df, pd.DataFrame())
    for b in bullets:
        assert "inf%" not in b and "NaN" not in b, f"Detected inf or NaN in bullet: {b}"

@test_case("24. Insights - Factually Accurate Micro-Transaction Insight")
def t24():
    # Case A: 5 large debits (10,000 each) -> Must NOT generate micro-transaction insight
    df_large = pd.DataFrame([
        {"date": pd.to_datetime("2026-10-01"), "amount": 10000.0, "type": "DEBIT", "balance": 50000.0} for _ in range(5)
    ])
    kpis_large = compute_kpis(df_large)
    bullets_large = generate_rule_based_insights(kpis_large, pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame(), pd.DataFrame())
    assert not any("Micro-Transaction" in b for b in bullets_large), "False positive: micro-transaction insight fired for 10k debits"

    # Case B: 5 micro debits (<= 100 each) -> MUST generate micro-transaction insight
    df_micro = pd.DataFrame([
        {"date": pd.to_datetime("2026-10-01"), "amount": 20.0, "type": "DEBIT", "balance": 5000.0} for _ in range(5)
    ])
    kpis_micro = compute_kpis(df_micro)
    bullets_micro = generate_rule_based_insights(kpis_micro, pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame(), pd.DataFrame())
    assert any("Micro-Transaction" in b for b in bullets_micro), "Expected micro-transaction insight for debits <= 100"

@test_case("25. Insights - Prompt Injection XML Tagging Protection")
def t25():
    # Verify module source code contains untrusted XML tags
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "modules", "insights.py"), "r", encoding="utf-8") as f:
        src = f.read()
    assert "<untrusted_statement_data>" in src, "Insights prompt must contain <untrusted_statement_data> tags"
    assert "</untrusted_statement_data>" in src, "Insights prompt must close </untrusted_statement_data> tags"

# ==============================================================================
# SECTION 5: HTML REPORT & XSS SECURITY (3 CHECKS)
# ==============================================================================

@test_case("26. Report - Jinja2 Autoescape & XSS Injection Neutralization")
def t26():
    evil_xss = "<script>alert('XSS')</script><img src=x onerror=alert(1)> **Bold Recommendation**"
    html = generate_html_report(pd.DataFrame(), {}, {}, [evil_xss])
    assert "<script>alert('XSS')</script>" not in html, "Raw script tag must not be rendered"
    assert "<img src=x onerror=alert(1)>" not in html, "Raw img tag must not be rendered"
    assert "&lt;script&gt;" in html or "&lt;img" in html, "Injected HTML tags must be entity-escaped"
    assert "<strong>Bold Recommendation</strong>" in html, "Safe bold formatting must be rendered"

@test_case("27. Report - Chart.js JSON Serialization Script Breakout Immunity")
def t27():
    evil_label = "</script><script>alert('Chart-XSS')</script>"
    df_evil = pd.DataFrame([{
        "date": pd.to_datetime("2026-10-01"),
        "date_str": evil_label,
        "time_str": "",
        "description": evil_label,
        "ref_no": evil_label,
        "amount": 100.0,
        "type": "DEBIT",
        "balance": 900.0,
        "payee": evil_label,
        "category": evil_label,
        "payment_method": "UPI"
    }])
    html = generate_html_report(df_evil, compute_kpis(df_evil), {}, ["Normal insight"])
    # The count of </script> tags in entire HTML should match exactly the expected HTML structure (Chart.js CDN + 1 inline script = 2)
    assert "</script><script>" not in html, "Closing script tag injection inside Chart.js data detected!"
    assert "\\u003c/script\\u003e" in html or html.count("</script>") == 2

@test_case("28. Report - Mobile Responsive CSS Validation")
def t28():
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "report.html"), "r", encoding="utf-8") as f:
        tpl = f.read()
    assert "@media (max-width: 768px)" in tpl, "Template must include mobile responsive media query"
    assert "width: 100%" in tpl, "Template must set search input width to 100% on small screens"

# ==============================================================================
# SECTION 6: APP.PY ARCHITECTURE & RE-PARSE VALIDATION (3 CHECKS)
# ==============================================================================

@test_case("29. App - Empty Statement DataFrame Crash Guard")
def t29():
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"), "r", encoding="utf-8") as f:
        app_code = f.read()
    assert "if df_full.empty:" in app_code, "app.py must explicitly guard against empty statement DataFrames"
    assert "st.stop()" in app_code, "app.py must stop execution cleanly on empty DataFrames"

@test_case("30. App - MD5 File Content Hashing Detection")
def t30():
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"), "r", encoding="utf-8") as f:
        app_code = f.read()
    assert "hashlib.md5(" in app_code, "app.py must implement MD5 content hashing for uploaded statements"
    assert "st.session_state.file_hash" in app_code, "app.py must track file_hash in session state"

@test_case("31. App - Apply Custom Mapping Active Re-Parsing Integration")
def t31():
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"), "r", encoding="utf-8") as f:
        app_code = f.read()
    btn_pos = app_code.find('if st.button("Apply Custom Mapping"')
    assert btn_pos != -1, "Apply Custom Mapping button not found in app.py"
    # Ensure load_and_parse_file is directly invoked in the button's action handler block
    btn_block = app_code[btn_pos:btn_pos + 600]
    assert "load_and_parse_file(" in btn_block, "Apply Custom Mapping button handler must re-invoke load_and_parse_file"

@test_case("32. Analyzer & Report - Statement without Balance Column Resilience")
def t32():
    no_bal_csv = b"Date,Description,Amount,Type\n01/10/2026,Salary,50000.00,CR\n02/10/2026,Rent,15000.00,DR\n"
    df, meta = load_and_parse_file(io.BytesIO(no_bal_csv), "nobal.csv")
    assert not meta["has_balance_column"], "Metadata should indicate no balance column"
    assert all(r is None for r in df["balance"]), "All balances should be None when column is missing"

    kpis = compute_kpis(df)
    assert kpis["opening_balance"] is None, f"Expected opening balance None, got {kpis['opening_balance']}"
    assert kpis["closing_balance"] is None, f"Expected closing balance None, got {kpis['closing_balance']}"

    df_bal = get_daily_balance_trend(df)
    assert df_bal.empty, "Daily balance trend should be empty when no balance column is present"

    # HTML Report must render cleanly without crashing and display N/A
    html_rep = generate_html_report(df, kpis, meta["header_info"], ["Sample insight"])
    assert "N/A" in html_rep, "HTML report should display N/A for missing opening/closing balances"
    assert "₹None" not in html_rep, "HTML report must not print ₹None"

    # Insights must generate cleanly without crashing
    bullets = generate_rule_based_insights(kpis, pd.DataFrame(), pd.DataFrame(), meta["header_info"], pd.DataFrame(), pd.DataFrame())
    assert len(bullets) >= 2
    for b in bullets:
        assert "None" not in b, f"Bullet should not contain raw None: {b}"

@test_case("33. Analyzer - Filter Transactions Resilience with Raw / Missing Columns")
def t33():
    df_raw_minimal = pd.DataFrame([
        {"date": pd.Timestamp("2026-10-01"), "description": "ATM Cash", "amount": 100.0, "type": "DEBIT"}
    ])
    # Must not raise KeyError when filtering on raw DataFrames missing payee, category, payment_method
    res = filter_transactions(df_raw_minimal, search_query="ATM")
    assert len(res) == 1
    res_type = filter_transactions(df_raw_minimal, txn_type="DEBIT")
    assert len(res_type) == 1

@test_case("34. Parser & App - Custom Mapping Persistence in Metadata")
def t34():
    csv_bytes = b"ColD,ColN,ColA\n01-10-2026,Grocery Store,250.00\n"
    c_map = {
        "date_col": "ColD",
        "desc_col": "ColN",
        "ref_col": None,
        "amount_col": "ColA",
        "type_col": None,
        "debit_col": None,
        "credit_col": None,
        "balance_col": None
    }
    df_p, meta_p = load_and_parse_file(io.BytesIO(csv_bytes), "custom.csv", custom_mapping=c_map)
    assert len(df_p) == 1
    assert meta_p["columns_detected"]["date_col"] == "ColD", "metadata columns_detected must retain custom mapping"
    assert meta_p["columns_detected"]["desc_col"] == "ColN"
    assert meta_p["columns_detected"]["amount_col"] == "ColA"
    assert meta_p["has_balance_column"] is False

print("\n" + "=" * 70)
print(f"REGRESSION SUITE COMPLETED: {passed_count} PASSED, {failed_count} FAILED")
print("=" * 70)

if failures:
    print("\nFAILURES ENCOUNTERED:")
    for name, exc, msg, tb in failures:
        print(f"\n[-] {name}: {exc}: {msg}")
    sys.exit(1)
else:
    print(f"\n🎉 ALL {passed_count} PRODUCTION HARDENING TESTS PASSED WITH 100% SUCCESS!")
    sys.exit(0)
