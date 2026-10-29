import os
import time
import io
import hashlib
from datetime import datetime
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from modules.parser import load_and_parse_file, auto_detect_columns
from modules.categorizer import enrich_and_categorize_dataframe
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
from modules.insights import generate_gemini_insights, generate_rule_based_insights, format_insight_to_html
from modules.report_generator import generate_html_report

load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Bank Statement Analyzer",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Dark Theme CSS
CUSTOM_CSS = """
<style>
    /* Dark background styling */
    .stApp {
        background-color: #0b0e1e;
        color: #f1f2f6;
    }
    
    /* Header card */
    .user-header-card {
        background: linear-gradient(135deg, #181d38 0%, #11142b 100%);
        border: 1px solid #283056;
        border-radius: 16px;
        padding: 22px 28px;
        margin-bottom: 24px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 16px;
    }
    
    .user-name-title {
        font-size: 24px;
        font-weight: 700;
        color: #ffffff;
        margin: 0;
        letter-spacing: 0.5px;
    }
    
    .meta-pill {
        display: inline-block;
        background: rgba(0, 206, 201, 0.12);
        color: #00cec9;
        border: 1px solid rgba(0, 206, 201, 0.3);
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 500;
        margin-right: 8px;
    }
    
    .meta-pill-secondary {
        display: inline-block;
        background: rgba(108, 92, 231, 0.12);
        color: #a29bfe;
        border: 1px solid rgba(108, 92, 231, 0.3);
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 500;
        margin-right: 8px;
    }

    /* KPI metric cards */
    .metric-card {
        background: #141830;
        border: 1px solid #232a50;
        border-radius: 14px;
        padding: 18px 22px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25);
        transition: transform 0.2s ease, border-color 0.2s ease;
        position: relative;
        overflow: hidden;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        border-color: rgba(0, 206, 201, 0.5);
    }
    .metric-title {
        font-size: 12px;
        text-transform: uppercase;
        color: #a4b0be;
        letter-spacing: 0.8px;
        font-weight: 600;
        margin-bottom: 6px;
    }
    .metric-val {
        font-size: 24px;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 4px;
    }
    .metric-sub {
        font-size: 12px;
        color: #747d8c;
    }
    
    /* Insight bullet styling */
    .insight-box {
        background: #151933;
        border: 1px solid #252d56;
        border-left: 4px solid #00cec9;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 12px;
        font-size: 14px;
        line-height: 1.6;
        color: #e4e7eb;
        box-shadow: 0 2px 10px rgba(0,0,0,0.15);
    }
    .insight-box strong {
        color: #ffffff;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        border-bottom: 1px solid #283056;
    }
    .stTabs [data-baseweb="tab"] {
        height: 48px;
        font-size: 15px;
        font-weight: 600;
        border-radius: 8px 8px 0px 0px;
        padding: 10px 20px;
        color: #a4b0be;
    }
    .stTabs [aria-selected="true"] {
        color: #00cec9 !important;
        background-color: rgba(0, 206, 201, 0.08) !important;
        border-bottom: 3px solid #00cec9 !important;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Session state initialization
if "df_raw" not in st.session_state:
    st.session_state.df_raw = None
if "df_processed" not in st.session_state:
    st.session_state.df_processed = None
if "metadata" not in st.session_state:
    st.session_state.metadata = None
if "insights_cache" not in st.session_state:
    st.session_state.insights_cache = None
if "active_file_name" not in st.session_state:
    st.session_state.active_file_name = None
if "file_hash" not in st.session_state:
    st.session_state.file_hash = None
if "active_file_bytes" not in st.session_state:
    st.session_state.active_file_bytes = None
if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = ""
if "insights_source" not in st.session_state:
    st.session_state.insights_source = None

# Sidebar
with st.sidebar:
    st.title("🏦 Statement Analyzer")
    st.caption("AI-Powered Multi-Bank Statement Analytics")
    st.divider()

    uploaded_file = st.file_uploader(
        "Upload Statement (CSV or Excel)",
        type=["csv", "xlsx", "xls"],
        help="Upload an account statement from any Indian bank (SBI, HDFC, ICICI, etc.)"
    )

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("📄 Load Sample Statement", use_container_width=True, help="Load your uploaded statement (sample_data/bank_statement_sample.xlsx)"):
            sample_path = os.path.join(os.path.dirname(__file__), "sample_data", "bank_statement_sample.xlsx")
            if os.path.exists(sample_path):
                with open(sample_path, "rb") as f:
                    file_bytes = f.read()
                df_p, meta = load_and_parse_file(io.BytesIO(file_bytes), "bank_statement_sample.xlsx")
                st.session_state.df_raw = df_p
                st.session_state.metadata = meta
                st.session_state.active_file_name = "bank_statement_sample.xlsx"
                st.session_state.active_file_bytes = file_bytes
                st.session_state.file_hash = hashlib.md5(file_bytes).hexdigest()
                st.session_state.df_processed = None
                st.session_state.insights_cache = None
                st.rerun()

    with col_btn2:
        if st.button("🏦 Test HDFC Format", use_container_width=True, help="Test multi-bank support with separate Debit/Credit columns"):
            sample_path = os.path.join(os.path.dirname(__file__), "sample_data", "hdfc_format_sample.csv")
            if os.path.exists(sample_path):
                with open(sample_path, "rb") as f:
                    file_bytes = f.read()
                df_p, meta = load_and_parse_file(io.BytesIO(file_bytes), "hdfc_format_sample.csv")
                st.session_state.df_raw = df_p
                st.session_state.metadata = meta
                st.session_state.active_file_name = "hdfc_format_sample.csv"
                st.session_state.active_file_bytes = file_bytes
                st.session_state.file_hash = hashlib.md5(file_bytes).hexdigest()
                st.session_state.df_processed = None
                st.session_state.insights_cache = None
                st.rerun()

    # Handle direct upload with MD5 content hashing
    if uploaded_file is not None:
        content_bytes = uploaded_file.getvalue()
        content_hash = hashlib.md5(content_bytes).hexdigest()
        if st.session_state.file_hash != content_hash:
            df_p, meta = load_and_parse_file(io.BytesIO(content_bytes), uploaded_file.name)
            st.session_state.df_raw = df_p
            st.session_state.metadata = meta
            st.session_state.active_file_name = uploaded_file.name
            st.session_state.active_file_bytes = content_bytes
            st.session_state.file_hash = content_hash
            st.session_state.df_processed = None
            st.session_state.insights_cache = None
            st.rerun()

    st.divider()

    # Column Mapping Expander
    if st.session_state.metadata is not None:
        with st.expander("🛠️ Column Mapping & Auto-Detection", expanded=False):
            st.info("Columns detected automatically. Adjust only if needed.")
            avail_cols = ["None"] + st.session_state.metadata.get("available_columns", [])
            detected = st.session_state.metadata.get("columns_detected", {})

            def get_index(col_key):
                val = detected.get(col_key)
                if val and val in avail_cols:
                    return avail_cols.index(val)
                return 0

            sel_date = st.selectbox("Date Column", avail_cols, index=get_index("date_col"))
            sel_desc = st.selectbox("Description Column", avail_cols, index=get_index("desc_col"))
            sel_ref = st.selectbox("Ref/Chq Column", avail_cols, index=get_index("ref_col"))
            sel_amt = st.selectbox("Amount Column", avail_cols, index=get_index("amount_col"))
            sel_type = st.selectbox("Type Column (Dr/Cr)", avail_cols, index=get_index("type_col"))
            sel_debit = st.selectbox("Debit Column (Optional)", avail_cols, index=get_index("debit_col"))
            sel_credit = st.selectbox("Credit Column (Optional)", avail_cols, index=get_index("credit_col"))
            sel_bal = st.selectbox("Balance Column", avail_cols, index=get_index("balance_col"))

            if st.button("Apply Custom Mapping", use_container_width=True):
                c_map = {k: (None if v == "None" else v) for k, v in [
                    ("date_col", sel_date), ("desc_col", sel_desc), ("ref_col", sel_ref), ("amount_col", sel_amt),
                    ("type_col", sel_type), ("debit_col", sel_debit), ("credit_col", sel_credit), ("balance_col", sel_bal)
                ]}
                if st.session_state.active_file_bytes is not None:
                    df_reparsed, meta_reparsed = load_and_parse_file(
                        io.BytesIO(st.session_state.active_file_bytes),
                        st.session_state.active_file_name or "uploaded_statement.csv",
                        custom_mapping=c_map
                    )
                    st.session_state.df_raw = df_reparsed
                    st.session_state.metadata = meta_reparsed
                elif st.session_state.metadata is not None:
                    st.session_state.metadata["columns_detected"] = c_map
                    
                st.session_state.df_processed = None
                st.session_state.insights_cache = None
                st.success("Custom mapping applied and file re-parsed!")
                st.rerun()

    # AI Categorization Settings
    use_ai = st.toggle("Enable Gemini AI Smart Categorization", value=True, help="Uses Gemini 3.5 Flash Lite to categorize ambiguous merchants and transactions.")

    # Check for server or user-provided Gemini API key
    server_key = os.getenv("GEMINI_API_KEY", "").strip()
    try:
        if not server_key and hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
            server_key = str(st.secrets["GEMINI_API_KEY"]).strip()
    except Exception:
        pass

    active_api_key = server_key or st.session_state.get("gemini_api_key", "").strip()

    if use_ai and not active_api_key:
        input_key = st.text_input(
            "🔑 Gemini API Key (Optional)",
            type="password",
            value=st.session_state.get("gemini_api_key", ""),
            help="To enable Gemini AI categorization and insights on the live app, enter your free API key from Google AI Studio. Stored in session only."
        )
        if input_key and input_key.strip():
            st.session_state.gemini_api_key = input_key.strip()
            active_api_key = input_key.strip()

    if st.session_state.df_raw is not None and st.session_state.df_processed is None:
        with st.spinner("Classifying and enriching statement transactions..."):
            df_enr = enrich_and_categorize_dataframe(st.session_state.df_raw, use_ai=use_ai, api_key=active_api_key)
            st.session_state.df_processed = df_enr

# Main Content Area
if st.session_state.df_processed is None:
    st.info("👋 Welcome! Please upload a bank statement (CSV or Excel) from the sidebar, or click **Load Sample Statement** to view the live dashboard immediately.")
    st.stop()

df_full = st.session_state.df_processed
metadata = st.session_state.metadata or {}
header_info = metadata.get("header_info", {})

# Guard against empty statement DataFrame
if df_full.empty:
    if metadata.get("error"):
        st.error(f"⚠️ **Error parsing statement:** {metadata['error']}")
    st.warning("⚠️ **No valid transactions could be found in the uploaded statement.**")
    st.info("Please verify that your file contains transaction rows and dates, or use the **🛠️ Column Mapping & Auto-Detection** panel in the sidebar to manually map columns.")
    st.stop()

# Extract header display fields safely
account_holder = header_info.get("account_holder") or "Account Holder"
if not df_full.empty and pd.notna(df_full["date"].min()):
    statement_period = header_info.get("period") or f"From {df_full['date'].min().strftime('%d/%m/%Y')} To {df_full['date'].max().strftime('%d/%m/%Y')}"
else:
    statement_period = header_info.get("period") or "Statement Period"
branch_name = header_info.get("branch") or "Pune Branch"
currency_code = header_info.get("currency") or "INR"

# Top Banner Card
st.markdown(f"""
<div class="user-header-card">
    <div>
        <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 0.8px; color: #a4b0be; margin-bottom: 4px;">Account Statement Analysis</div>
        <h2 class="user-name-title">{account_holder}</h2>
        <div style="margin-top: 8px;">
            <span class="meta-pill">📅 {statement_period}</span>
            <span class="meta-pill-secondary">📍 {branch_name}</span>
            <span class="meta-pill">💱 {currency_code}</span>
        </div>
    </div>
    <div style="text-align: right;">
        <span style="font-size: 13px; color: #a4b0be;">Total Entries</span>
        <div style="font-size: 28px; font-weight: 700; color: #ffffff;">{len(df_full)}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# Filters Row (Interactive Slicers)
with st.expander("🔍 Interactive Slicers & Filters", expanded=True):
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    
    with col_f1:
        # Date range filter guarded against NaT / empty
        if not df_full.empty and pd.notna(df_full["date"].min()):
            min_date = df_full["date"].min().date()
            max_date = df_full["date"].max().date()
        else:
            min_date = datetime.now().date()
            max_date = datetime.now().date()
        date_selection = st.date_input("Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
        if isinstance(date_selection, (tuple, list)) and len(date_selection) == 2:
            start_d, end_d = date_selection
        else:
            start_d, end_d = min_date, max_date

    with col_f2:
        type_options = ["ALL", "DEBIT", "CREDIT"]
        selected_type = st.selectbox("Transaction Type", type_options, index=0)

    with col_f3:
        all_methods = ["ALL"] + sorted(df_full["payment_method"].dropna().unique().tolist())
        selected_method = st.selectbox("Payment Method", all_methods, index=0)

    with col_f4:
        all_categories = ["ALL"] + sorted(df_full["category"].dropna().unique().tolist())
        selected_category = st.selectbox("Spending Category", all_categories, index=0)

# Apply filters
df_filtered = filter_transactions(
    df_full,
    start_date=start_d,
    end_date=end_d,
    txn_type=selected_type,
    payment_method=selected_method,
    category=selected_category
)

# Compute filtered KPIs
kpis = compute_kpis(df_filtered)

# 3 Main Tabs Navigation
tab_dash, tab_txns, tab_insights = st.tabs(["📊 Executive Dashboard", "🔍 Transactions & Search", "💡 AI Insights & Report"])

# ----------------- TAB 1: EXECUTIVE DASHBOARD -----------------
with tab_dash:
    # 6 KPI Cards Grid
    col_k1, col_k2, col_k3, col_k4, col_k5, col_k6 = st.columns(6)
    
    with col_k1:
        st.markdown(f"""
        <div class="metric-card" style="border-top: 3px solid #00b894;">
            <div class="metric-title">💰 Total Credits</div>
            <div class="metric-val" style="color: #00b894;">₹{kpis['total_credits']:,.2f}</div>
            <div class="metric-sub">{kpis['credit_count']} inflow credits</div>
        </div>
        """, unsafe_allow_html=True)

    with col_k2:
        st.markdown(f"""
        <div class="metric-card" style="border-top: 3px solid #ff7675;">
            <div class="metric-title">💸 Total Debits</div>
            <div class="metric-val" style="color: #ff7675;">₹{kpis['total_debits']:,.2f}</div>
            <div class="metric-sub">{kpis['debit_count']} outflow debits</div>
        </div>
        """, unsafe_allow_html=True)

    with col_k3:
        net_color = "#00b894" if kpis['net_cash_flow'] >= 0 else "#ff7675"
        plus_sign = "+" if kpis['net_cash_flow'] >= 0 else ""
        st.markdown(f"""
        <div class="metric-card" style="border-top: 3px solid {net_color};">
            <div class="metric-title">⚖️ Net Cash Flow</div>
            <div class="metric-val" style="color: {net_color};">{plus_sign}₹{kpis['net_cash_flow']:,.2f}</div>
            <div class="metric-sub">{'Surplus cash' if kpis['net_cash_flow'] >= 0 else 'Deficit cash'}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_k4:
        closing_txt = f"₹{kpis['closing_balance']:,.2f}" if kpis.get('closing_balance') is not None else "N/A"
        opening_txt = f"Opening: ₹{kpis['opening_balance']:,.2f}" if kpis.get('opening_balance') is not None else "Opening: N/A"
        st.markdown(f"""
        <div class="metric-card" style="border-top: 3px solid #00cec9;">
            <div class="metric-title">🏦 Closing Balance</div>
            <div class="metric-val">{closing_txt}</div>
            <div class="metric-sub">{opening_txt}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_k5:
        st.markdown(f"""
        <div class="metric-card" style="border-top: 3px solid #6c5ce7;">
            <div class="metric-title">📊 Transactions</div>
            <div class="metric-val">{kpis['total_transactions']}</div>
            <div class="metric-sub">Avg Debit: ₹{kpis['avg_debit']:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_k6:
        st.markdown(f"""
        <div class="metric-card" style="border-top: 3px solid #fdcb6e;">
            <div class="metric-title">⚡ Peak Outflow</div>
            <div class="metric-val" style="font-size: 20px;">₹{kpis['max_debit']['amount']:,.2f}</div>
            <div class="metric-sub">{kpis['max_debit']['payee'][:16]}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Plotly Visualizations (Dark Theme)
    plotly_layout_dark = dict(
        paper_bgcolor="#141830",
        plot_bgcolor="#141830",
        font=dict(color="#f1f2f6", family="sans-serif"),
        margin=dict(l=30, r=30, t=40, b=30)
    )

    # Row 1: Balance Trend (Line) + Payment Method Distribution (Donut)
    col_c1, col_c2 = st.columns([2, 1])

    with col_c1:
        st.subheader("📈 Daily Account Balance Trend")
        df_bal = get_daily_balance_trend(df_filtered)
        if not df_bal.empty:
            fig_bal = go.Figure()
            fig_bal.add_trace(go.Scatter(
                x=df_bal["date_str"],
                y=df_bal["closing_balance"],
                mode="lines+markers",
                name="Closing Balance",
                line=dict(color="#00cec9", width=3),
                fill="tozeroy",
                fillcolor="rgba(0, 206, 201, 0.12)",
                marker=dict(size=6, color="#00cec9")
            ))
            fig_bal.update_layout(
                **plotly_layout_dark,
                height=320,
                yaxis_title="Balance (₹)",
                hovermode="x unified"
            )
            fig_bal.update_xaxes(gridcolor="#283056", showgrid=True)
            fig_bal.update_yaxes(gridcolor="#283056", showgrid=True)
            st.plotly_chart(fig_bal, use_container_width=True)
        else:
            st.info("No balance trend data for selected filter.")

    with col_c2:
        st.subheader("🍩 Payment Methods")
        df_methods = get_payment_methods_summary(df_filtered)
        if not df_methods.empty:
            fig_pie = px.pie(
                df_methods,
                names="payment_method",
                values="count",
                hole=0.65,
                color_discrete_sequence=["#00cec9", "#6c5ce7", "#fdcb6e", "#ff7675", "#55efc4", "#74b9ff"]
            )
            fig_pie.update_layout(
                paper_bgcolor="#141830",
                plot_bgcolor="#141830",
                font=dict(color="#f1f2f6"),
                height=320,
                margin=dict(l=10, r=10, t=30, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No payment methods data.")

    # Row 2: Category Breakdown + Top Payees
    col_c3, col_c4 = st.columns(2)

    with col_c3:
        st.subheader("📊 Spending by Category")
        df_cat = get_category_spending(df_filtered).head(8)
        if not df_cat.empty:
            fig_cat = px.bar(
                df_cat,
                x="total_amount",
                y="category",
                orientation="h",
                text="total_amount",
                color_discrete_sequence=["#6c5ce7"]
            )
            fig_cat.update_traces(
                texttemplate="₹%{text:,.2f}",
                textposition="outside",
                marker=dict(line=dict(color="#a29bfe", width=1))
            )
            fig_cat.update_layout(
                **plotly_layout_dark,
                height=320,
                xaxis_title="Outflow (₹)",
                yaxis_title=""
            )
            fig_cat.update_xaxes(gridcolor="#283056", showgrid=True)
            fig_cat.update_yaxes(gridcolor="#283056", showgrid=False, autorange="reversed")
            st.plotly_chart(fig_cat, use_container_width=True)
        else:
            st.info("No category spending data for selected filter.")

    with col_c4:
        st.subheader("👥 Top 10 Payees / Recipients")
        df_top_p = get_top_payees(df_filtered, top_n=10)
        if not df_top_p.empty:
            fig_payees = px.bar(
                df_top_p,
                x="total_amount",
                y="payee",
                orientation="h",
                text="total_amount",
                color_discrete_sequence=["#ff7675"]
            )
            fig_payees.update_traces(
                texttemplate="₹%{text:,.2f}",
                textposition="outside",
                marker=dict(line=dict(color="#fab1a0", width=1))
            )
            fig_payees.update_layout(
                **plotly_layout_dark,
                height=320,
                xaxis_title="Outflow (₹)",
                yaxis_title=""
            )
            fig_payees.update_xaxes(gridcolor="#283056", showgrid=True)
            fig_payees.update_yaxes(gridcolor="#283056", showgrid=False, autorange="reversed")
            st.plotly_chart(fig_payees, use_container_width=True)
        else:
            st.info("No payees data for selected filter.")

    # Row 3: Weekly Credits vs Debits
    st.subheader("⚖️ Weekly Cash Flow (Credits vs Debits)")
    df_weekly = get_weekly_flow(df_filtered)
    if not df_weekly.empty:
        fig_week = go.Figure()
        fig_week.add_trace(go.Bar(
            x=df_weekly["week_start"],
            y=df_weekly["credits"],
            name="Credits (Inflow)",
            marker_color="#00b894"
        ))
        fig_week.add_trace(go.Bar(
            x=df_weekly["week_start"],
            y=df_weekly["debits"],
            name="Debits (Outflow)",
            marker_color="#ff7675"
        ))
        fig_week.update_layout(
            **plotly_layout_dark,
            height=300,
            barmode="group",
            yaxis_title="Amount (₹)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        fig_week.update_xaxes(gridcolor="#283056", showgrid=True)
        fig_week.update_yaxes(gridcolor="#283056", showgrid=True)
        st.plotly_chart(fig_week, use_container_width=True)

# ----------------- TAB 2: TRANSACTIONS & SEARCH -----------------
with tab_txns:
    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        search_query = st.text_input(
            "🔍 Search Transactions",
            placeholder="Type UPI Ref No., Payee Name, Amount, Narration, or Category to filter instantly...",
            key="tx_search"
        )
    with col_s2:
        quick_view = st.selectbox(
            "Quick Filter",
            ["All Transactions", "⚠️ Flagged Anomalies", "🔁 Recurring Payments", "👥 Potential Duplicates"]
        )

    # Process search query & quick view
    df_tx_display = filter_transactions(df_filtered, search_query=search_query)

    if quick_view == "⚠️ Flagged Anomalies":
        anomalies_df = detect_anomalies(df_tx_display)
        st.warning(f"🚨 Detected {len(anomalies_df)} unusually large transactions (> 2σ from mean):")
        df_tx_display = anomalies_df
    elif quick_view == "👥 Potential Duplicates":
        dups_df = detect_duplicates(df_tx_display)
        st.warning(f"👥 Found {len(dups_df)} potential duplicate transactions (same date, amount, payee):")
        df_tx_display = dups_df
    elif quick_view == "🔁 Recurring Payments":
        recurring_df = detect_recurring_transactions(df_tx_display)
        st.info(f"🔁 Found {len(recurring_df)} recurring payees:")
        st.dataframe(recurring_df, use_container_width=True)

    # Stats display
    st.caption(f"Showing **{len(df_tx_display)}** of **{len(df_full)}** total transactions")

    # Format table for display
    display_cols = ["date_str", "time_str", "payee", "category", "payment_method", "ref_no", "amount", "type", "balance"]
    existing_cols = [c for c in display_cols if c in df_tx_display.columns]

    df_view = df_tx_display[existing_cols].copy()
    df_view.rename(columns={
        "date_str": "Date",
        "time_str": "Time",
        "payee": "Payee / Counterparty",
        "category": "Spending Category",
        "payment_method": "Method",
        "ref_no": "Ref / Chq No.",
        "amount": "Amount (₹)",
        "type": "Type",
        "balance": "Balance (₹)"
    }, inplace=True)

    # Display interactive table
    st.dataframe(
        df_view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Amount (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Balance (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        }
    )

    # CSV Download Button
    csv_bytes = df_view.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Export Filtered Transactions as CSV",
        data=csv_bytes,
        file_name="processed_bank_transactions.csv",
        mime="text/csv"
    )

    st.divider()

    # Detailed Transaction Inspector
    st.subheader("🔎 Transaction Detail Inspector")
    if not df_tx_display.empty:
        tx_options = [f"#{i+1} | {r['date_str']} | ₹{r['amount']:,.2f} {r['type']} | {r['payee']}" for i, r in df_tx_display.reset_index(drop=True).iterrows()]
        selected_tx_idx = st.selectbox("Select a transaction to inspect its complete metadata:", range(len(tx_options)), format_func=lambda i: tx_options[i])
        
        sel_row = df_tx_display.reset_index(drop=True).iloc[selected_tx_idx]
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            st.metric("Amount & Type", f"₹{sel_row['amount']:,.2f}", delta=sel_row['type'])
            st.write(f"**Date:** {sel_row['date_str']} {sel_row['time_str']}")
            bal_txt = f"₹{sel_row['balance']:,.2f}" if (pd.notna(sel_row.get('balance')) and sel_row.get('balance') is not None) else "N/A"
            st.write(f"**Closing Balance:** {bal_txt}")
        with col_t2:
            st.write(f"**Payee:** {sel_row['payee']}")
            st.write(f"**Category:** {sel_row['category']}")
            st.write(f"**Method:** {sel_row['payment_method']}")
        with col_t3:
            st.write(f"**Ref / Chq No.:** `{sel_row['ref_no']}`")
            st.write(f"**Full Narration:**")
            st.info(sel_row['description'])

# ----------------- TAB 3: AI INSIGHTS & REPORT -----------------
with tab_insights:
    st.subheader("💡 Financial Intelligence & Strategic Recommendations")

    # Engine status caption
    if active_api_key:
        st.caption("🤖 Powered by Google Gemini AI (gemini-3.5-flash-lite) • Personalized Financial Analysis")
    else:
        st.caption("⚡ Powered by High-Precision Smart Financial Rules • Enter a Gemini API Key to enable AI reasoning")

    # Optional inline API Key input if not provided via environment or sidebar
    if not active_api_key:
        with st.expander("🔑 Unlock Gemini Generative AI Reasoning (Free)", expanded=False):
            st.markdown(
                "By default, the dashboard generates high-precision deterministic financial insights. "
                "To unlock deep AI reasoning and personalized recommendations, enter your free Gemini API key from [Google AI Studio](https://aistudio.google.com/):"
            )
            col_k1, col_k2 = st.columns([3, 1])
            with col_k1:
                tab_key_val = st.text_input("Gemini API Key", type="password", key="tab3_gemini_key_input", label_visibility="collapsed")
            with col_k2:
                if st.button("Activate AI", use_container_width=True, key="btn_apply_tab_key"):
                    if tab_key_val and tab_key_val.strip():
                        st.session_state.gemini_api_key = tab_key_val.strip()
                        st.session_state.insights_cache = None
                        st.session_state.insights_source = None
                        st.rerun()

    col_act1, col_act2 = st.columns([3, 1])
    with col_act2:
        regenerate_btn = st.button("🔄 Regenerate AI Insights", use_container_width=True)

    # Generate or fetch cached insights
    if st.session_state.insights_cache is None or regenerate_btn:
        with st.spinner("Analyzing spending trends and financial health..."):
            cat_df = get_category_spending(df_full)
            payees_df = get_top_payees(df_full)
            anom_df = detect_anomalies(df_full)
            rec_df = detect_recurring_transactions(df_full)

            insights_list, is_rate_limited, wait_seconds, source = generate_gemini_insights(
                kpis=compute_kpis(df_full),
                cat_df=cat_df,
                payees_df=payees_df,
                header_info=header_info,
                anom_df=anom_df,
                rec_df=rec_df,
                api_key=active_api_key,
                return_source=True
            )

            st.session_state.insights_cache = insights_list
            st.session_state.insights_source = source

            if regenerate_btn:
                if source == "gemini":
                    st.toast("✨ Successfully regenerated fresh AI insights via Gemini!", icon="🤖")
                elif source == "rate_limited":
                    st.toast("⏳ Gemini free tier limit reached (15 RPM). Rule-based insights loaded.", icon="⏳")
                elif source == "no_key":
                    st.toast("🔄 Insights refreshed using Smart Financial Rules.", icon="💡")
                else:
                    st.toast("🔄 Insights updated successfully.", icon="💡")

    # Feedback callouts
    current_source = st.session_state.get("insights_source")
    if current_source == "rate_limited":
        st.warning("⏳ **Gemini API free tier rate limit (15 requests/min) reached.**")
        st.info("💡 High-precision deterministic insights have been generated as an instant fallback below. You can click **Regenerate AI Insights** once your quota renews.")
    elif current_source == "gemini" and regenerate_btn:
        st.success("🤖 Fresh AI-powered insights generated via Google Gemini AI!")
    elif current_source in ("no_key", "error") and regenerate_btn:
        st.info("💡 Displaying high-precision rule-based insights. Enter your Gemini API key to enable personalized AI reasoning.")

    # Render insights bullet points with HTML strong tags (eliminating raw asterisks)
    insights_to_show = st.session_state.insights_cache or []
    for bullet in insights_to_show:
        formatted_bullet = format_insight_to_html(bullet)
        st.markdown(f'<div class="insight-box">{formatted_bullet}</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    # Standalone HTML Report Generation & Download
    st.subheader("📥 Export Standalone Interactive HTML Report")
    st.write("Generate a self-contained, offline-compatible HTML report with embedded Chart.js visualizations, interactive search table, KPI cards, and AI insights.")

    # Generate HTML report string
    report_html = generate_html_report(
        df=df_full,
        kpis=compute_kpis(df_full),
        header_info=header_info,
        insights=insights_to_show
    )

    col_dl1, col_dl2 = st.columns([1, 2])
    with col_dl1:
        st.download_button(
            label="⬇️ Download Full HTML Report",
            data=report_html,
            file_name=f"bank_statement_report_{account_holder.replace(' ', '_').lower()}.html",
            mime="text/html",
            use_container_width=True
        )

    with st.expander("👁️ Preview HTML Report in Browser Window", expanded=False):
        st.components.v1.html(report_html, height=800, scrolling=True)
