import os
import json
import html
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
from markupsafe import Markup
from jinja2 import Environment, FileSystemLoader, select_autoescape

from modules.analyzer import (
    get_daily_balance_trend,
    get_payment_methods_summary,
    get_category_spending,
    get_top_payees,
    get_weekly_flow
)

def safe_chartjs_json(data: Any) -> Markup:
    """
    Safely serializes data to JSON for use inside HTML <script> tags.
    Escapes <, >, and & characters using unicode escapes to prevent
    closing script tag injection (</script>) and XSS vulnerabilities.
    Wraps the output in markupsafe.Markup so Jinja2 with autoescape=True
    does not escape quotes into &#34; inside Javascript blocks.
    """
    raw_json = json.dumps(data)
    safe_str = (
        raw_json
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return Markup(safe_str)

def sanitize_insight_bullet(bullet: str) -> Markup:
    """
    Escapes HTML entities in insight text, then safely converts **bold** to <strong>bold</strong>.
    Returns markupsafe.Markup so formatting tags are rendered while raw HTML injections are neutralized.
    """
    escaped = html.escape(str(bullet))
    formatted = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    return Markup(formatted)

def prepare_chart_data(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Extracts structured JSON-serializable chart data for Chart.js rendering in HTML report.
    """
    if df.empty:
        return {
            "balance_trend": {"labels": [], "data": []},
            "payment_methods": {"labels": [], "data": []},
            "categories": {"labels": [], "data": []},
            "top_payees": {"labels": [], "data": []},
            "weekly_flow": {"labels": [], "credits": [], "debits": []}
        }

    df_safe = df.copy()
    if "payment_method" not in df_safe.columns:
        df_safe["payment_method"] = "Other"
    if "category" not in df_safe.columns:
        df_safe["category"] = "Miscellaneous / Other"
    if "payee" not in df_safe.columns:
        df_safe["payee"] = df_safe["description"] if "description" in df_safe.columns else "Unknown"

    # 1. Balance Trend
    df_balance = get_daily_balance_trend(df_safe)
    balance_trend = {
        "labels": df_balance["date_str"].tolist() if not df_balance.empty else [],
        "data": [float(x) for x in df_balance["closing_balance"].tolist() if x is not None and not pd.isna(x)] if not df_balance.empty else []
    }
    
    # 2. Payment Methods
    df_methods = get_payment_methods_summary(df_safe)
    payment_methods = {
        "labels": df_methods["payment_method"].tolist() if not df_methods.empty else [],
        "data": [int(x) for x in df_methods["count"].tolist()] if not df_methods.empty else []
    }
    
    # 3. Categories (top 8)
    df_cat = get_category_spending(df_safe).head(8)
    categories = {
        "labels": df_cat["category"].tolist() if not df_cat.empty else [],
        "data": [float(x) for x in df_cat["total_amount"].tolist()] if not df_cat.empty else []
    }
    
    # 4. Top 10 Payees
    df_payees = get_top_payees(df_safe, top_n=10)
    top_payees = {
        "labels": df_payees["payee"].tolist() if not df_payees.empty else [],
        "data": [float(x) for x in df_payees["total_amount"].tolist()] if not df_payees.empty else []
    }
    
    # 5. Weekly Flow
    df_weekly = get_weekly_flow(df_safe)
    weekly_flow = {
        "labels": df_weekly["week_start"].tolist() if not df_weekly.empty else [],
        "credits": [float(x) for x in df_weekly["credits"].tolist()] if not df_weekly.empty else [],
        "debits": [float(x) for x in df_weekly["debits"].tolist()] if not df_weekly.empty else []
    }
    
    return {
        "balance_trend": balance_trend,
        "payment_methods": payment_methods,
        "categories": categories,
        "top_payees": top_payees,
        "weekly_flow": weekly_flow
    }

def generate_html_report(
    df: pd.DataFrame,
    kpis: Dict[str, Any],
    header_info: Dict[str, Any],
    insights: List[str],
    output_path: Optional[str] = None
) -> str:
    """
    Renders the interactive dark-themed standalone HTML report using Jinja2 and Chart.js.
    Enforces autoescape=True for XSS protection and uses safe_chartjs_json filter for script blocks.
    Returns the HTML string and optionally saves to output_path.
    """
    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(['html', 'xml'])
    )
    # Register filters for both safe_chartjs_json and tojson
    env.filters["safe_chartjs_json"] = safe_chartjs_json
    env.filters["tojson"] = safe_chartjs_json
    
    template = env.get_template("report.html")
    
    default_kpis = {
        "total_credits": 0.0,
        "total_debits": 0.0,
        "net_cash_flow": 0.0,
        "opening_balance": None,
        "closing_balance": None,
        "total_transactions": 0,
        "credit_count": 0,
        "debit_count": 0,
        "avg_debit": 0.0,
        "avg_credit": 0.0,
        "max_debit": {"amount": 0.0, "payee": "-", "date": "-"},
        "max_credit": {"amount": 0.0, "payee": "-", "date": "-"}
    }
    safe_kpis = {**default_kpis, **(kpis or {})}
    if not isinstance(safe_kpis.get("max_debit"), dict):
        safe_kpis["max_debit"] = {"amount": 0.0, "payee": "-", "date": "-"}
    if not isinstance(safe_kpis.get("max_credit"), dict):
        safe_kpis["max_credit"] = {"amount": 0.0, "payee": "-", "date": "-"}
    
    chart_data = prepare_chart_data(df)
    sanitized_insights = [sanitize_insight_bullet(b) for b in (insights or [])]
    
    # Convert transactions to dict records
    records = df.to_dict(orient="records") if not df.empty else []
    
    html_content = template.render(
        header_info=header_info or {},
        kpis=safe_kpis,
        insights=sanitized_insights,
        transactions=records,
        chart_data=chart_data,
        generated_on=datetime.now().strftime("%d %b %Y, %I:%M %p")
    )
    
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
    return html_content
