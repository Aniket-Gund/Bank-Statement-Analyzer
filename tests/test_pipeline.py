import os
import sys
from datetime import datetime

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Configure UTF-8 output for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from modules.parser import load_and_parse_file, auto_detect_columns
from modules.categorizer import enrich_and_categorize_dataframe
from modules.analyzer import (
    compute_kpis,
    get_category_spending,
    get_payment_methods_summary,
    get_top_payees,
    get_daily_balance_trend,
    get_weekly_flow,
    detect_duplicates,
    detect_anomalies,
    detect_recurring_transactions,
    filter_transactions
)
from modules.insights import generate_gemini_insights
from modules.report_generator import generate_html_report

print("=" * 60)
print("TEST 1: Loading & Parsing Bank Statement (Exact User Match)")
print("=" * 60)

excel_path = "sample_data/bank_statement_sample.xlsx"
with open(excel_path, "rb") as f:
    df, meta = load_and_parse_file(f, "bank_statement_sample.xlsx")

print("Header Metadata:", meta["header_info"])
assert meta["header_info"]["account_holder"] == "RAHUL ARUN SHARMA", f"Unexpected holder: {meta['header_info']['account_holder']}"
assert "01/10/2026" in meta["header_info"]["period"], f"Unexpected period: {meta['header_info']['period']}"
assert len(df) == 25, f"Expected 25 rows, got {len(df)}"
print(f"SUCCESS: Loaded 25 transactions for {meta['header_info']['account_holder']}.")

print("\n" + "=" * 60)
print("TEST 2: Enrichment & Hybrid Categorization")
print("=" * 60)

df_enriched = enrich_and_categorize_dataframe(df, use_ai=True)
print("Enriched Columns:", df_enriched.columns.tolist())
assert "payee" in df_enriched.columns
assert "payment_method" in df_enriched.columns
assert "category" in df_enriched.columns
print("Sample Enriched Rows:")
for idx, r in df_enriched.head(5).iterrows():
    print(f" - {r['date_str']} | {r['type']} ₹{r['amount']} | {r['payee']} | {r['payment_method']} | {r['category']}")

print("\n" + "=" * 60)
print("TEST 3: Financial KPIs Verification")
print("=" * 60)

kpis = compute_kpis(df_enriched)
print(f"Total Credits: ₹{kpis['total_credits']:,.2f}")
print(f"Total Debits:  ₹{kpis['total_debits']:,.2f}")
print(f"Net Cash Flow: ₹{kpis['net_cash_flow']:,.2f}")
print(f"Opening Bal:   ₹{kpis['opening_balance']:,.2f}")
print(f"Closing Bal:   ₹{kpis['closing_balance']:,.2f}")
print(f"Total Count:   {kpis['total_transactions']}")

assert round(kpis["total_credits"], 2) == 69700.00, f"Credits mismatch: {kpis['total_credits']}"
assert round(kpis["total_debits"], 2) == 40914.70, f"Debits mismatch: {kpis['total_debits']}"
assert round(kpis["closing_balance"], 2) == 34035.30, f"Closing balance mismatch: {kpis['closing_balance']}"
print("SUCCESS: All financial figures match the dummy statement dataset with 100% precision.")

print("\n" + "=" * 60)
print("TEST 4: Groupings & Advanced Analytics (Bonus Features)")
print("=" * 60)

dups = detect_duplicates(df_enriched)
print(f"Detected Duplicates: {len(dups)} rows")

anoms = detect_anomalies(df_enriched)
print(f"Detected Anomalies:  {len(anoms)} rows")

recs = detect_recurring_transactions(df_enriched)
print(f"Recurring Payees:    {len(recs)} counterparties")

print("\n" + "=" * 60)
print("TEST 5: Free-Text Search & Filtering")
print("=" * 60)

# Search by Ref No
ref_search = filter_transactions(df_enriched, search_query="718291029388")
print(f"Search for ref '718291029388': {len(ref_search)} row found ({ref_search.iloc[0]['payee']}, ₹{ref_search.iloc[0]['amount']})")
assert len(ref_search) == 1
assert "Sunil Joshi" in ref_search.iloc[0]["payee"] or "Rent" in ref_search.iloc[0]["payee"]

# Search by Payee
starbucks_search = filter_transactions(df_enriched, search_query="starbucks")
print(f"Search for 'starbucks': {len(starbucks_search)} rows found")
assert len(starbucks_search) == 1

print("\n" + "=" * 60)
print("TEST 6: Gemini AI Insights Generation & Rate-Limit Handling")
print("=" * 60)

cat_df = get_category_spending(df_enriched)
payees_df = get_top_payees(df_enriched)

insights, is_rate_limited, wait_sec = generate_gemini_insights(
    kpis=kpis,
    cat_df=cat_df,
    payees_df=payees_df,
    header_info=meta["header_info"],
    anom_df=anoms,
    rec_df=recs
)

print(f"Generated {len(insights)} insights (Rate Limited: {is_rate_limited}):")
for i, b in enumerate(insights, 1):
    print(f"  {i}. {b}")
assert len(insights) >= 5

print("\n" + "=" * 60)
print("TEST 7: Self-Contained Standalone HTML Report Generation")
print("=" * 60)

report_file = "bank_statement_report.html"
html_out = generate_html_report(
    df=df_enriched,
    kpis=kpis,
    header_info=meta["header_info"],
    insights=insights,
    output_path=report_file
)
assert os.path.exists(report_file)
size_kb = os.path.getsize(report_file) / 1024
print(f"SUCCESS: Generated {report_file} ({size_kb:.1f} KB).")

print("\n" + "=" * 60)
print("TEST 8: Multi-Bank Statement Support (HDFC Format)")
print("=" * 60)

with open("sample_data/hdfc_format_sample.csv", "rb") as f2:
    df_hdfc, meta_hdfc = load_and_parse_file(f2, "hdfc_format_sample.csv")

df_hdfc_enr = enrich_and_categorize_dataframe(df_hdfc, use_ai=False)
kpis_hdfc = compute_kpis(df_hdfc_enr)
print(f"HDFC Parsed Rows: {len(df_hdfc_enr)}")
print(f"HDFC Total Credits: ₹{kpis_hdfc['total_credits']:,.2f}")
print(f"HDFC Total Debits:  ₹{kpis_hdfc['total_debits']:,.2f}")
assert len(df_hdfc_enr) == 8
print("SUCCESS: Multi-bank statement auto-detection and parsing verified!")

print("\n" + "=" * 60)
print("ALL 8 VERIFICATION TESTS PASSED SUCCESSFULLY!")
print("=" * 60)
