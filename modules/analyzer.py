import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional

def _safe_mode_category(s: pd.Series) -> str:
    """Safely computes the mode category without crashing on empty or all-NaN series."""
    cleaned = s.dropna()
    if not cleaned.empty:
        m = cleaned.mode()
        if not m.empty:
            return str(m.iloc[0])
    return "Other"

def compute_kpis(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Computes all essential financial KPIs from the enriched transactions DataFrame.
    Accurately supports overdraft / negative balances and avoids division by zero.
    """
    if df.empty:
        return {
            "total_credits": 0.0,
            "total_debits": 0.0,
            "net_cash_flow": 0.0,
            "opening_balance": None,
            "closing_balance": None,
            "total_transactions": 0,
            "credit_count": 0,
            "debit_count": 0,
            "micro_debit_count": 0,
            "avg_debit": 0.0,
            "avg_credit": 0.0,
            "max_debit": {"amount": 0.0, "payee": "-", "date": "-", "desc": "-"},
            "max_credit": {"amount": 0.0, "payee": "-", "date": "-", "desc": "-"}
        }
        
    df_sorted = df.sort_values(by="date", kind="mergesort").reset_index(drop=True)
    
    debits = df_sorted[df_sorted["type"] == "DEBIT"]
    credits = df_sorted[df_sorted["type"] == "CREDIT"]
    
    total_debits = float(debits["amount"].sum()) if not debits.empty else 0.0
    total_credits = float(credits["amount"].sum()) if not credits.empty else 0.0
    net_cash_flow = total_credits - total_debits
    
    # Calculate opening and closing balance:
    # If the statement has no balance column at all (or all balances are NaN/None),
    # set opening and closing balances to None.
    has_valid_balance = False
    if "balance" in df_sorted.columns:
        valid_bals = df_sorted["balance"].dropna()
        if not valid_bals.empty and any(b is not None for b in valid_bals):
            has_valid_balance = True

    if not has_valid_balance:
        opening_balance = None
        closing_balance = None
    else:
        first_row = df_sorted.iloc[0]
        first_bal = first_row.get("balance")
        first_amt = float(first_row.get("amount", 0.0))
        if first_bal is None or pd.isna(first_bal):
            opening_balance = None
        else:
            first_bal = float(first_bal)
            if first_row.get("type") == "DEBIT":
                opening_balance = first_bal + first_amt
            else:
                opening_balance = first_bal - first_amt
                
        last_bal = df_sorted.iloc[-1].get("balance")
        closing_balance = float(last_bal) if (last_bal is not None and not pd.isna(last_bal)) else None
    
    # Max debit
    if not debits.empty:
        max_deb_row = debits.loc[debits["amount"].idxmax()]
        max_debit = {
            "amount": float(max_deb_row["amount"]),
            "payee": str(max_deb_row.get("payee", "-")),
            "date": str(max_deb_row.get("date_str", "-")),
            "desc": str(max_deb_row.get("description", "-"))
        }
    else:
        max_debit = {"amount": 0.0, "payee": "-", "date": "-", "desc": "-"}
        
    # Max credit
    if not credits.empty:
        max_cred_row = credits.loc[credits["amount"].idxmax()]
        max_credit = {
            "amount": float(max_cred_row["amount"]),
            "payee": str(max_cred_row.get("payee", "-")),
            "date": str(max_cred_row.get("date_str", "-")),
            "desc": str(max_cred_row.get("description", "-"))
        }
    else:
        max_credit = {"amount": 0.0, "payee": "-", "date": "-", "desc": "-"}
        
    avg_debit = float(debits["amount"].mean()) if not debits.empty else 0.0
    avg_credit = float(credits["amount"].mean()) if not credits.empty else 0.0
    micro_debit_count = int((debits["amount"] <= 100.0).sum()) if not debits.empty else 0
    
    return {
        "total_credits": total_credits,
        "total_debits": total_debits,
        "net_cash_flow": net_cash_flow,
        "opening_balance": opening_balance,
        "closing_balance": closing_balance,
        "total_transactions": len(df_sorted),
        "credit_count": len(credits),
        "debit_count": len(debits),
        "micro_debit_count": micro_debit_count,
        "avg_debit": avg_debit,
        "avg_credit": avg_credit,
        "max_debit": max_debit,
        "max_credit": max_credit
    }

def get_category_spending(df: pd.DataFrame) -> pd.DataFrame:
    """Computes total debit spending grouped by spending category."""
    if df.empty or "type" not in df.columns or "amount" not in df.columns or "category" not in df.columns:
        return pd.DataFrame(columns=["category", "total_amount", "count", "percentage"])
        
    debits = df[df["type"] == "DEBIT"]
    if debits.empty:
        return pd.DataFrame(columns=["category", "total_amount", "count", "percentage"])
        
    grouped = debits.groupby("category")["amount"].agg(total_amount="sum", count="count").reset_index()
    total_spend = grouped["total_amount"].sum()
    grouped["percentage"] = (grouped["total_amount"] / total_spend * 100).round(1) if total_spend > 0 else 0.0
    return grouped.sort_values(by="total_amount", ascending=False).reset_index(drop=True)

def get_category_inflow(df: pd.DataFrame) -> pd.DataFrame:
    """Computes total credit inflow grouped by category."""
    if df.empty or "type" not in df.columns or "amount" not in df.columns or "category" not in df.columns:
        return pd.DataFrame(columns=["category", "total_amount", "count"])
    credits = df[df["type"] == "CREDIT"]
    if credits.empty:
        return pd.DataFrame(columns=["category", "total_amount", "count"])
    grouped = credits.groupby("category")["amount"].agg(total_amount="sum", count="count").reset_index()
    return grouped.sort_values(by="total_amount", ascending=False).reset_index(drop=True)

def get_payment_methods_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Computes distribution by payment method (UPI, Card, NEFT, etc.)."""
    if df.empty or "amount" not in df.columns or "payment_method" not in df.columns:
        return pd.DataFrame(columns=["payment_method", "total_amount", "count", "debit_amount", "credit_amount"])
        
    grouped = df.groupby("payment_method").agg(
        total_amount=("amount", "sum"),
        count=("amount", "count")
    ).reset_index()
    
    debit_sums = df[df["type"] == "DEBIT"].groupby("payment_method")["amount"].sum().to_dict() if "type" in df.columns else {}
    credit_sums = df[df["type"] == "CREDIT"].groupby("payment_method")["amount"].sum().to_dict() if "type" in df.columns else {}
    
    grouped["debit_amount"] = grouped["payment_method"].map(lambda m: debit_sums.get(m, 0.0))
    grouped["credit_amount"] = grouped["payment_method"].map(lambda m: credit_sums.get(m, 0.0))
    
    return grouped.sort_values(by="total_amount", ascending=False).reset_index(drop=True)

def get_top_payees(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Returns top N recipients / payees by total debit amount."""
    if df.empty or "type" not in df.columns or "amount" not in df.columns or "payee" not in df.columns:
        return pd.DataFrame(columns=["payee", "total_amount", "count", "category"])
        
    debits = df[df["type"] == "DEBIT"]
    if debits.empty:
        return pd.DataFrame(columns=["payee", "total_amount", "count", "category"])
        
    agg_kwargs = {
        "total_amount": ("amount", "sum"),
        "count": ("amount", "count")
    }
    if "category" in debits.columns:
        agg_kwargs["category"] = ("category", _safe_mode_category)
    else:
        agg_kwargs["category"] = ("amount", lambda _: "Other")
        
    grouped = debits.groupby("payee").agg(**agg_kwargs).reset_index()
    return grouped.sort_values(by="total_amount", ascending=False).head(top_n).reset_index(drop=True)

def get_top_payers(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Returns top N senders / sources of credit inflow."""
    if df.empty or "type" not in df.columns or "amount" not in df.columns or "payee" not in df.columns:
        return pd.DataFrame(columns=["payee", "total_amount", "count"])
    credits = df[df["type"] == "CREDIT"]
    if credits.empty:
        return pd.DataFrame(columns=["payee", "total_amount", "count"])
    grouped = credits.groupby("payee").agg(
        total_amount=("amount", "sum"),
        count=("amount", "count")
    ).reset_index()
    return grouped.sort_values(by="total_amount", ascending=False).head(top_n).reset_index(drop=True)

def get_daily_balance_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Returns chronological daily ending balance and daily net flow."""
    if df.empty or "balance" not in df.columns or df["balance"].dropna().empty or not any(b is not None for b in df["balance"].dropna()):
        return pd.DataFrame(columns=["date", "date_str", "closing_balance", "daily_credits", "daily_debits"])
        
    df_sorted = df.sort_values(by="date", kind="mergesort").copy()
    df_sorted["date_only"] = df_sorted["date"].dt.date
    
    daily_records = []
    for day, group in df_sorted.groupby("date_only", sort=True):
        last_bal_val = group.iloc[-1].get("balance")
        if last_bal_val is None or pd.isna(last_bal_val):
            continue
        last_balance = float(last_bal_val)
        credits_sum = group[group["type"] == "CREDIT"]["amount"].sum()
        debits_sum = group[group["type"] == "DEBIT"]["amount"].sum()
        
        daily_records.append({
            "date": pd.to_datetime(day),
            "date_str": day.strftime("%d-%m-%Y"),
            "closing_balance": last_balance,
            "daily_credits": float(credits_sum),
            "daily_debits": float(debits_sum)
        })
        
    if not daily_records:
        return pd.DataFrame(columns=["date", "date_str", "closing_balance", "daily_credits", "daily_debits"])
        
    res = pd.DataFrame(daily_records).sort_values(by="date").reset_index(drop=True)
    return res

def get_weekly_flow(df: pd.DataFrame) -> pd.DataFrame:
    """
    Groups transactions by week in strict chronological order for stacked bar chart comparisons.
    Uses period sort instead of alphabetical string sorting.
    """
    if df.empty:
        return pd.DataFrame(columns=["week_start", "credits", "debits"])
        
    df_sorted = df.sort_values(by="date", kind="mergesort").copy()
    df_sorted["week_period"] = df_sorted["date"].dt.to_period("W-SUN")
    
    records = []
    for period, grp in df_sorted.groupby("week_period", sort=True):
        label = period.start_time.strftime("%d %b")
        cred = grp[grp["type"] == "CREDIT"]["amount"].sum()
        deb = grp[grp["type"] == "DEBIT"]["amount"].sum()
        records.append({
            "week_start": label,
            "credits": float(cred),
            "debits": float(deb)
        })
    return pd.DataFrame(records)

def get_monthly_spending_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly debits vs credits breakdown in chronological sequence."""
    if df.empty:
        return pd.DataFrame(columns=["month", "debits", "credits", "net"])
    df_c = df.sort_values(by="date", kind="mergesort").copy()
    df_c["month_period"] = df_c["date"].dt.to_period("M")
    
    records = []
    for period, grp in df_c.groupby("month_period", sort=True):
        m_label = period.start_time.strftime("%Y-%m (%b)")
        deb = grp[grp["type"] == "DEBIT"]["amount"].sum()
        cred = grp[grp["type"] == "CREDIT"]["amount"].sum()
        records.append({
            "month": m_label,
            "debits": float(deb),
            "credits": float(cred),
            "net": float(cred - deb)
        })
    return pd.DataFrame(records)

def detect_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identifies potential duplicate transactions: same date, same amount, same payee/type.
    """
    if df.empty or len(df) < 2:
        return pd.DataFrame()
        
    df_c = df.copy()
    candidate_sub = [c for c in ["date_str", "amount", "payee", "type"] if c in df_c.columns]
    if len(candidate_sub) < 2:
        candidate_sub = [c for c in ["date", "amount", "description"] if c in df_c.columns]
    if len(candidate_sub) < 2:
        return pd.DataFrame()
        
    dup_mask = df_c.duplicated(subset=candidate_sub, keep=False)
    sort_cols = [c for c in ["date", "amount"] if c in df_c.columns]
    return df_c[dup_mask].sort_values(by=sort_cols) if sort_cols else df_c[dup_mask]

def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detects high-value transaction anomalies (> mean + 1.8*std or top 8% amount).
    Guards against zero-variance datasets (does not flag 100% of transactions when amounts are identical).
    """
    if df.empty or "type" not in df.columns or "amount" not in df.columns:
        return pd.DataFrame()
        
    debits = df[df["type"] == "DEBIT"]
    if len(debits) < 4:
        return pd.DataFrame()
        
    amounts = debits["amount"]
    # If all amounts are identical or standard deviation is 0, there are no anomalies
    if amounts.nunique() <= 1 or amounts.std() == 0.0 or pd.isna(amounts.std()):
        return pd.DataFrame()
        
    mean_val = float(amounts.mean())
    std_val = float(amounts.std())
    threshold = max(mean_val + (1.8 * std_val), float(amounts.quantile(0.92)))
    
    # Do not flag if threshold matches or is lower than min
    if threshold <= amounts.min():
        return pd.DataFrame()

    anomalies = debits[debits["amount"] >= threshold].sort_values(by="amount", ascending=False)
    # Ensure anomalies does not encompass all transactions
    if len(anomalies) == len(debits):
        return pd.DataFrame()
        
    return anomalies

def detect_recurring_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identifies frequent or recurring transactions (paid to same payee 2 or more times).
    """
    if df.empty or "type" not in df.columns or "amount" not in df.columns:
        return pd.DataFrame()
        
    payee_col = "payee" if "payee" in df.columns else ("description" if "description" in df.columns else None)
    if not payee_col:
        return pd.DataFrame()
        
    debits = df[df["type"] == "DEBIT"]
    if debits.empty:
        return pd.DataFrame()
        
    agg_kwargs = {
        "frequency": ("amount", "count"),
        "total_amount": ("amount", "sum"),
        "avg_amount": ("amount", "mean")
    }
    if "category" in debits.columns:
        agg_kwargs["category"] = ("category", "first")
        
    counts = debits.groupby(payee_col).agg(**agg_kwargs).reset_index()
    if payee_col != "payee":
        counts.rename(columns={payee_col: "payee"}, inplace=True)
        
    recurring = counts[counts["frequency"] >= 2].sort_values(by="frequency", ascending=False)
    return recurring

def filter_transactions(
    df: pd.DataFrame,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    txn_type: str = "ALL",
    payment_method: str = "ALL",
    category: str = "ALL",
    search_query: str = ""
) -> pd.DataFrame:
    """
    Filters transactions by date range, type, payment method, category, and free-text search.
    Enforces regex=False on all string search lookups to prevent regex injection crashes.
    Defensively guards against missing columns.
    """
    if df.empty:
        return df.copy()

    filtered = df.copy()
    
    if start_date and "date" in filtered.columns:
        filtered = filtered[filtered["date"] >= pd.to_datetime(start_date)]
    if end_date and "date" in filtered.columns:
        # Include through end of day
        filtered = filtered[filtered["date"] <= pd.to_datetime(end_date) + pd.Timedelta(days=1, microseconds=-1)]
        
    if txn_type != "ALL" and "type" in filtered.columns:
        filtered = filtered[filtered["type"] == txn_type]
        
    if payment_method != "ALL" and "payment_method" in filtered.columns:
        filtered = filtered[filtered["payment_method"] == payment_method]
        
    if category != "ALL" and "category" in filtered.columns:
        filtered = filtered[filtered["category"] == category]
        
    if search_query:
        query = str(search_query).strip()
        if query:
            match_masks = []
            for col in ["description", "payee", "ref_no", "category", "payment_method"]:
                if col in filtered.columns:
                    match_masks.append(filtered[col].astype(str).str.contains(query, case=False, regex=False, na=False))
            if "amount" in filtered.columns:
                match_masks.append(filtered["amount"].astype(str).str.contains(query, case=False, regex=False, na=False))
                
            if match_masks:
                combined_mask = match_masks[0]
                for m in match_masks[1:]:
                    combined_mask = combined_mask | m
                filtered = filtered[combined_mask]
        
    return filtered
