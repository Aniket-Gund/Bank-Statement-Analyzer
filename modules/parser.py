import re
import io
import math
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Tuple, Dict, Any, Optional

def is_amount_negative(val: Any) -> bool:
    """Detects if a raw amount represents an explicitly negative value (e.g. reversal or outflow)."""
    if pd.isna(val) or val is None:
        return False
    if isinstance(val, (int, float)):
        return val < 0
    s = str(val).strip()
    if not s:
        return False
    s_clean = re.sub(r'(?i)\b(?:inr|rs)\b\.?', '', s)
    s_clean = re.sub(r'[₹$€£¥\s]', '', s_clean)
    if s_clean.startswith('(') and s_clean.endswith(')'):
        return True
    if s_clean.startswith('-') or s_clean.endswith('-'):
        return True
    return False

def is_amount_positive_signed(val: Any) -> bool:
    """Detects if a raw amount explicitly specifies a positive sign (+)."""
    if pd.isna(val) or val is None:
        return False
    if isinstance(val, (int, float)):
        return val > 0
    s = str(val).strip()
    if not s:
        return False
    s_clean = re.sub(r'(?i)\b(?:inr|rs)\b\.?', '', s)
    s_clean = re.sub(r'[₹$€£¥\s]', '', s_clean)
    if s_clean.startswith('+') or s_clean.endswith('+'):
        return True
    return False

def is_single_amount_credit(val: Any) -> bool:
    """Detects if a single-amount column value indicates an inflow/credit via sign or CR indicator."""
    if pd.isna(val) or val is None:
        return False
    if is_amount_positive_signed(val):
        return True
    s = str(val).strip().upper()
    if re.search(r'\bCR\b|(?<=\d)\s*CR', s):
        return True
    return False

def is_single_amount_debit(val: Any) -> bool:
    """Detects if a single-amount column value indicates an outflow/debit via sign or DR indicator."""
    if pd.isna(val) or val is None:
        return False
    if is_amount_negative(val):
        return True
    s = str(val).strip().upper()
    if re.search(r'\bDR\b|(?<=\d)\s*DR', s):
        return True
    return False

def clean_amount(val: Any) -> float:
    """
    Safely converts string or number to positive float amount.
    Handles international currencies ($ € £ ¥ ₹ Rs. INR), accounting parentheses (1,234.50),
    trailing minus 100-, European decimals (1.234,50), and eliminates NaN / Inf.
    """
    if pd.isna(val) or val is None:
        return 0.0
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return abs(float(val))
        
    s = str(val).strip()
    if not s:
        return 0.0
        
    s_lower = s.lower()
    if s_lower in ['nan', 'none', 'null', 'inf', '-inf', 'infinity', '-infinity', '--', 'n/a', 'na', '-', 'nil']:
        return 0.0
        
    # Strip currency signs & common text without touching decimal dot
    s = re.sub(r'(?i)\b(?:inr|rs)\b\.?', '', s)
    s = re.sub(r'[₹$€£¥\s]', '', s)
    s = re.sub(r'(?i)(?:cr|dr)\b', '', s).strip()
    
    # Strip parentheses and signs
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1]
    if s.endswith('-') or s.startswith('-'):
        s = s.replace('-', '')
    if s.endswith('+') or s.startswith('+'):
        s = s.replace('+', '')
        
    # Handle European decimal: e.g. 1.234,50 or 1234,50
    if '.' in s and ',' in s:
        if s.rfind(',') > s.rfind('.'):
            # dot is thousand separator, comma is decimal
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        # If comma followed by 1 or 2 digits at end (e.g. 1234,50), treat as decimal comma
        if re.search(r',\d{1,2}$', s):
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
            
    try:
        f = float(s)
        if math.isnan(f) or math.isinf(f):
            return 0.0
        return abs(f)
    except ValueError:
        m = re.search(r'\d*\.?\d+', s)
        if m:
            try:
                f = float(m.group(0))
                return 0.0 if (math.isnan(f) or math.isinf(f)) else abs(f)
            except ValueError:
                return 0.0
        return 0.0

def extract_header_info(df_raw: pd.DataFrame) -> Dict[str, Any]:
    """
    Extracts customer name, statement period, account no, branch, etc.
    from raw rows before the transaction table.
    """
    info = {
        "account_holder": "",
        "period": "",
        "account_no": "",
        "branch": "",
        "currency": "INR",
        "raw_text_header": []
    }
    
    if df_raw is None or df_raw.empty or len(df_raw.columns) == 0:
        return info
    
    # Iterate through first ~20 rows looking for key phrases
    max_rows = min(20, len(df_raw))
    potential_names = []
    
    for i in range(max_rows):
        row_values = [str(x).strip() for x in df_raw.iloc[i].values if pd.notna(x) and str(x).strip() != '']
        if not row_values:
            continue
        
        row_str = " | ".join(row_values)
        info["raw_text_header"].append(row_str)
        
        # Check for Period
        period_match = re.search(r'(?:Period|Duration|From|Between)[:\s]*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}\s*(?:To|to|-)\s*[0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})', row_str, re.IGNORECASE)
        if period_match and not info["period"]:
            info["period"] = period_match.group(1).strip()
        elif "from" in row_str.lower() and "to" in row_str.lower() and not info["period"]:
            p_sub = re.search(r'From\s+([^\s|]+)\s+To\s+([^\s|]+)', row_str, re.IGNORECASE)
            if p_sub:
                info["period"] = f"{p_sub.group(1)} to {p_sub.group(2)}"
        
        # Check for Account No
        acc_match = re.search(r'(?:Account\s*(?:No|Number)|A/c\s*(?:No)?)[.:\s]*([A-Za-z0-9\-X]+)', row_str, re.IGNORECASE)
        if acc_match and not info["account_no"] and acc_match.group(1).upper() not in ['STATEMENT', 'DETAILS']:
            info["account_no"] = acc_match.group(1).strip()
            
        # Check for Branch
        branch_match = re.search(r'(?:Branch|Sol\s*Id)[.:\s|]*([A-Za-z0-9\s,]+?)(?:\||$)', row_str, re.IGNORECASE)
        if branch_match and not info["branch"]:
            b_val = branch_match.group(1).strip()
            if b_val and b_val.upper() not in ['NAME', 'CODE', '']:
                info["branch"] = b_val
            
        # Check for Currency
        curr_match = re.search(r'(?:Currency)[:\s]*([A-Z]{3})', row_str, re.IGNORECASE)
        if curr_match:
            info["currency"] = curr_match.group(1).strip()

        # Check for Account Holder Name
        name_match = re.search(r'(?:Name|Customer\s*Name|A/c\s*Name|Holder)[:\s]*([A-Za-z\s.]+)', row_str, re.IGNORECASE)
        if name_match and not info["account_holder"]:
            info["account_holder"] = name_match.group(1).strip()
        else:
            # If line is an uppercase name-like string (e.g. "RAHUL ARUN SHARMA")
            first_val = row_values[0]
            if re.match(r'^[A-Z\s.]{4,40}$', first_val) and not any(kw in first_val for kw in ['STATEMENT', 'ACCOUNT', 'BANK', 'LIMITED', 'BRANCH', 'PAGE', 'SL.']):
                potential_names.append(first_val)

    if not info["account_holder"] and potential_names:
        info["account_holder"] = potential_names[0].strip()
        
    return info

def find_table_header_index(df_raw: pd.DataFrame) -> int:
    """
    Finds the row index where the actual transactions table headers begin.
    """
    if df_raw is None or df_raw.empty or len(df_raw.columns) == 0:
        return 0

    header_keywords = [
        'date', 'txn', 'transaction', 'narration', 'description', 
        'particulars', 'amount', 'balance', 'debit', 'credit', 
        'dr', 'cr', 'chq', 'cheque', 'ref', 'withdrawal', 'deposit', 'sl'
    ]
    
    max_scan = min(30, len(df_raw))
    best_idx = 0
    max_score = 0
    
    for i in range(max_scan):
        row_vals = [str(x).lower().strip() for x in df_raw.iloc[i].values if pd.notna(x)]
        score = sum(1 for v in row_vals if any(kw in v for kw in header_keywords))
        # Extra weight if contains both date and amount/balance/debit/credit
        has_date = any('date' in v for v in row_vals)
        has_money = any(k in v for v in row_vals for k in ['amount', 'balance', 'debit', 'credit', 'withdrawal', 'deposit'])
        if has_date and has_money:
            score += 3
        if score > max_score:
            max_score = score
            best_idx = i
            
    return best_idx

def auto_detect_columns(columns: list) -> Dict[str, Optional[str]]:
    """
    Detects which column corresponds to date, description, ref_no, amount, type, debit, credit, balance.
    """
    mapping = {
        "date_col": None,
        "desc_col": None,
        "ref_col": None,
        "amount_col": None,
        "type_col": None,
        "debit_col": None,
        "credit_col": None,
        "balance_col": None
    }
    
    cols_clean = [str(c).strip() for c in columns]
    cols_lower = [c.lower() for c in cols_clean]
    
    # 1. Date column
    for i, c in enumerate(cols_lower):
        if 'txn date' in c or 'trans date' in c or 'transaction date' in c:
            mapping["date_col"] = cols_clean[i]
            break
    if not mapping["date_col"]:
        for i, c in enumerate(cols_lower):
            if 'date' in c and 'value' not in c:
                mapping["date_col"] = cols_clean[i]
                break
    if not mapping["date_col"]:
        for i, c in enumerate(cols_lower):
            if 'date' in c:
                mapping["date_col"] = cols_clean[i]
                break
                
    # 2. Description column
    for kw in ['description', 'narration', 'particulars', 'details', 'remarks']:
        for i, c in enumerate(cols_lower):
            if kw in c:
                mapping["desc_col"] = cols_clean[i]
                break
        if mapping["desc_col"]:
            break
            
    # 3. Ref/Chq column
    for kw in ['ref', 'chq', 'cheque', 'utr', 'trans id', 'txn id', 'reference']:
        for i, c in enumerate(cols_lower):
            if kw in c and c != mapping["desc_col"]:
                mapping["ref_col"] = cols_clean[i]
                break
        if mapping["ref_col"]:
            break
            
    # 4. Check for separate Debit / Credit columns
    for i, c in enumerate(cols_lower):
        if ('withdrawal' in c or 'debit' in c) and ('type' not in c and 'dr/cr' not in c and c != 'dr' and c != 'cr'):
            mapping["debit_col"] = cols_clean[i]
        elif ('deposit' in c or 'credit' in c) and ('type' not in c and 'dr/cr' not in c and c != 'dr' and c != 'cr'):
            mapping["credit_col"] = cols_clean[i]
            
    # 5. Check for single Amount column
    if not (mapping["debit_col"] and mapping["credit_col"]):
        for i, c in enumerate(cols_lower):
            if ('amount' in c or 'txn amt' in c or 'transaction amt' in c) and c != mapping["balance_col"]:
                mapping["amount_col"] = cols_clean[i]
                break
        if not mapping["amount_col"]:
            for i, c in enumerate(cols_lower):
                if c == 'amount' or 'amt' in c:
                    mapping["amount_col"] = cols_clean[i]
                    break

    # 6. Check for Type (Dr/Cr) column
    for i, c in enumerate(cols_lower):
        if c in ['dr / cr', 'dr/cr', 'type', 'cr/dr', 'dr /cr', 'dr/ cr', 'cr / dr', 'cr/dr.', 'dr/cr.'] or ('type' in c and 'txn' not in c):
            if mapping["type_col"] is None:
                mapping["type_col"] = cols_clean[i]
            break

    # 7. Balance column
    for i, c in enumerate(cols_lower):
        if 'balance' in c or 'closing' in c or 'bal' in c:
            mapping["balance_col"] = cols_clean[i]
            break

    return mapping

def load_and_parse_file(file_obj, filename: str, custom_mapping: Optional[Dict[str, str]] = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Reads an uploaded CSV or Excel file, auto-detects structure & delimiters,
    cleans amounts, dates, and reversals, and returns (cleaned_dataframe, metadata).
    Handles empty files, semicolon/tab CSVs, and Excel serial dates gracefully.
    """
    empty_df = pd.DataFrame(columns=["date", "date_str", "time_str", "description", "ref_no", "amount", "type", "balance"])
    default_metadata = {
        "header_info": {
            "account_holder": "",
            "period": "",
            "account_no": "",
            "branch": "",
            "currency": "INR",
            "raw_text_header": []
        },
        "columns_detected": {},
        "available_columns": [],
        "total_raw_rows": 0,
        "parsed_rows_count": 0,
        "error": None
    }

    is_excel = filename.endswith('.xlsx') or filename.endswith('.xls')
    df_raw = None
    
    if is_excel:
        try:
            df_raw = pd.read_excel(file_obj, header=None)
        except Exception as e:
            default_metadata["error"] = f"Failed to read Excel file: {e}"
            return empty_df, default_metadata
    else:
        try:
            content = file_obj.read()
        except Exception as e:
            default_metadata["error"] = f"Failed to read file: {e}"
            return empty_df, default_metadata
            
        if isinstance(content, str):
            content = content.encode('utf-8')
        if not content or len(content.strip()) == 0:
            default_metadata["error"] = "Empty file provided"
            return empty_df, default_metadata

        # Try reading csv with python engine to auto-detect delimiters (',', ';', '\t', '|')
        for enc in ['utf-8', 'latin-1', 'cp1252']:
            try:
                df_raw = pd.read_csv(io.BytesIO(content), header=None, encoding=enc, sep=None, engine='python')
                if df_raw is not None and not df_raw.empty:
                    break
            except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError, ValueError):
                continue
            except Exception:
                continue

        # Delimiter fallback if sniffing failed
        if df_raw is None or df_raw.empty:
            for sep in [',', ';', '\t', '|']:
                for enc in ['utf-8', 'latin-1']:
                    try:
                        df_raw = pd.read_csv(io.BytesIO(content), header=None, encoding=enc, sep=sep)
                        if df_raw is not None and not df_raw.empty:
                            break
                    except Exception:
                        continue
                if df_raw is not None and not df_raw.empty:
                    break

    if df_raw is None or df_raw.empty or len(df_raw.columns) == 0:
        default_metadata["error"] = "No tabular data could be parsed from the file"
        return empty_df, default_metadata

    # Extract header metadata before slicing table
    header_info = extract_header_info(df_raw)
    
    # Locate header row index
    header_idx = find_table_header_index(df_raw)
    
    # If file has fewer rows than header_idx + 1
    if header_idx >= len(df_raw):
        default_metadata["error"] = "Header index out of bounds"
        return empty_df, default_metadata

    # Take table slice
    raw_headers = df_raw.iloc[header_idx].values
    
    # Handle duplicate header names (e.g. multiple 'Dr / Cr' columns)
    header_counts = {}
    unique_headers = []
    for h in raw_headers:
        name = str(h).strip() if pd.notna(h) and str(h).strip() != '' else 'Unnamed'
        if name in header_counts:
            header_counts[name] += 1
            unique_headers.append(f"{name}_{header_counts[name]}")
        else:
            header_counts[name] = 1
            unique_headers.append(name)
            
    df_table = df_raw.iloc[header_idx + 1:].copy()
    if df_table.empty:
        default_metadata["available_columns"] = unique_headers
        default_metadata["header_info"] = header_info
        return empty_df, default_metadata
        
    df_table.columns = unique_headers
    df_table = df_table.dropna(how='all')
    
    # Get column mapping (either auto-detected or customized)
    auto_mapping = auto_detect_columns(unique_headers)
    active_mapping = custom_mapping if custom_mapping else auto_mapping
    
    # Parse rows into standard structure
    parsed_rows = []
    
    date_col = active_mapping.get("date_col")
    desc_col = active_mapping.get("desc_col")
    ref_col = active_mapping.get("ref_col")
    amount_col = active_mapping.get("amount_col")
    type_col = active_mapping.get("type_col")
    debit_col = active_mapping.get("debit_col")
    credit_col = active_mapping.get("credit_col")
    balance_col = active_mapping.get("balance_col")
    
    for idx, row in df_table.iterrows():
        # Check if this is a total / summary row
        desc_val = str(row[desc_col]).strip() if desc_col and desc_col in row and pd.notna(row[desc_col]) else ""
        if any(term in desc_val.lower() for term in ['total', 'grand total', 'opening balance', 'closing balance']) and not any(kw in desc_val.upper() for kw in ['UPI', 'NEFT', 'IMPS', 'ATM', 'CHRG']):
            continue
            
        # Parse Date
        date_raw = str(row[date_col]).strip() if date_col and date_col in row and pd.notna(row[date_col]) else ""
        if not date_raw or date_raw.lower() in ['nan', 'none', '']:
            continue
            
        parsed_date = pd.NaT
        # 1. Check if date is Excel serial integer/float (typically 1000 - 100000)
        m_serial = re.match(r'^(\d{4,6})(\.\d+)?$', date_raw)
        if m_serial:
            try:
                serial_num = float(date_raw)
                if 1000 <= serial_num <= 100000:
                    parsed_date = pd.to_datetime(serial_num, unit='D', origin='1899-12-30')
            except Exception:
                pass
                
        # 2. Standard pd.to_datetime
        if pd.isna(parsed_date):
            parsed_date = pd.to_datetime(date_raw, dayfirst=True, errors='coerce')
            
        # 3. Clean 12-hour or 24-hour timestamps (e.g. '01/10/2026, 3:15 pm' or '01-10-2026 14:30:00')
        if pd.isna(parsed_date):
            date_clean = re.sub(r'(?i)[,\s]+\d{1,2}:\d{2}(?::\d{2})?(\s*[ap]m)?', '', date_raw).strip()
            date_clean = date_clean.rstrip(',. ')
            parsed_date = pd.to_datetime(date_clean, dayfirst=True, errors='coerce')
            
        # 4. Fallback explicit formats
        if pd.isna(parsed_date):
            for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%Y/%m/%d"]:
                try:
                    parsed_date = pd.to_datetime(datetime.strptime(date_raw, fmt))
                    break
                except (ValueError, TypeError):
                    continue
            
        if pd.isna(parsed_date):
            continue  # Skip row if valid date cannot be found
            
        # Parse Ref/Chq No
        ref_val = str(row[ref_col]).strip() if ref_col and ref_col in row and pd.notna(row[ref_col]) else ""
        if (not ref_val or ref_val.lower() == 'nan') and desc_val:
            # Extract from description if available
            upi_ref = re.search(r'UPI[-/]([A-Za-z0-9]+)', desc_val)
            if upi_ref:
                ref_val = upi_ref.group(0)
            else:
                num_ref = re.search(r'\b\d{10,14}\b', desc_val)
                if num_ref:
                    ref_val = num_ref.group(0)
                else:
                    ref_val = "-"
                    
        # Parse Amount and Type
        amount = 0.0
        txn_type = "DEBIT"
        
        if debit_col and credit_col and debit_col in row and credit_col in row:
            raw_deb = row[debit_col]
            raw_cred = row[credit_col]
            deb_val = clean_amount(raw_deb)
            cred_val = clean_amount(raw_cred)
            deb_is_neg = is_amount_negative(raw_deb)
            cred_is_neg = is_amount_negative(raw_cred)
            
            if cred_val > 0:
                if cred_is_neg:
                    # Negative in Credit column -> reversal of credit = DEBIT
                    amount = cred_val
                    txn_type = "DEBIT"
                else:
                    amount = cred_val
                    txn_type = "CREDIT"
            elif deb_val > 0:
                if deb_is_neg:
                    # Negative in Debit column -> reversal of debit = CREDIT
                    amount = deb_val
                    txn_type = "CREDIT"
                else:
                    amount = deb_val
                    txn_type = "DEBIT"
        elif amount_col and amount_col in row:
            raw_amt_val = str(row[amount_col]).strip()
            amount = clean_amount(raw_amt_val)
            
            # Determine type
            if type_col and type_col in row and pd.notna(row[type_col]):
                t_str = str(row[type_col]).strip().upper()
                if t_str in ['CR', 'C', 'CREDIT'] or 'CR' in t_str or t_str.startswith('CR'):
                    txn_type = "CREDIT"
                elif t_str in ['DR', 'D', 'DEBIT'] or 'DR' in t_str or t_str.startswith('DR'):
                    txn_type = "DEBIT"
                else:
                    txn_type = "DEBIT"
            else:
                # No type column: analyze amount sign and description keywords
                if is_single_amount_debit(raw_amt_val):
                    txn_type = "DEBIT"
                elif is_single_amount_credit(raw_amt_val):
                    txn_type = "CREDIT"
                else:
                    # Check description keywords for credit vs debit indicators
                    desc_lower = desc_val.lower()
                    credit_kws = ['salary', 'refund', 'interest', 'cashback', 'dividend', 'reversal', 'deposit', 'credited', 'credit received', 'bonus']
                    debit_kws = ['withdrawal', 'purchase', 'paid to', 'transfer to', 'spent', 'atm', 'pos', 'charge', 'fee', 'emi', 'debit']
                    
                    has_cred_kw = any(k in desc_lower for k in credit_kws)
                    has_deb_kw = any(k in desc_lower for k in debit_kws)
                    
                    if has_cred_kw and not has_deb_kw:
                        txn_type = "CREDIT"
                    elif has_deb_kw and not has_cred_kw:
                        txn_type = "DEBIT"
                    else:
                        txn_type = "DEBIT"  # default
        else:
            continue
            
        # Parse Balance (None if column is missing or blank)
        balance = None
        if balance_col and balance_col in row and pd.notna(row[balance_col]):
            raw_bal_str = str(row[balance_col]).strip()
            if raw_bal_str and raw_bal_str.lower() not in ['nan', 'none', 'null', '--', 'n/a', '-', 'nil']:
                bal_val = clean_amount(raw_bal_str)
                # Check for overdraft negative balance e.g. -500, (500), or 500 DR
                if is_amount_negative(raw_bal_str) or 'DR' in raw_bal_str.upper():
                    balance = -bal_val
                else:
                    balance = bal_val
            
        parsed_rows.append({
            "date": parsed_date,
            "date_str": parsed_date.strftime("%d-%m-%Y"),
            "time_str": parsed_date.strftime("%H:%M") if parsed_date.hour != 0 or parsed_date.minute != 0 else "",
            "description": desc_val,
            "ref_no": ref_val,
            "amount": amount,
            "type": txn_type,
            "balance": balance
        })
        
    if parsed_rows:
        # Determine if statement was in reverse chronological order in raw file
        first_date = parsed_rows[0]["date"]
        last_date = parsed_rows[-1]["date"]
        is_reverse_order = False
        if len(parsed_rows) >= 2:
            if first_date > last_date:
                is_reverse_order = True
            elif first_date == last_date:
                # Compare balances top-to-bottom
                b0 = parsed_rows[0]["balance"]
                b1 = parsed_rows[1]["balance"]
                a0 = parsed_rows[0]["amount"]
                if b0 is not None and b1 is not None and a0 > 0:
                    if abs((b0 - b1) - a0) < max(1.0, a0 * 0.05) or abs((b0 - b1) - (-a0)) < max(1.0, a0 * 0.05):
                        is_reverse_order = True

        if is_reverse_order:
            parsed_rows.reverse()

        # Running balance delta adjustment for single-amount statements without explicit type column
        if amount_col and not (debit_col and credit_col) and not type_col:
            for i in range(1, len(parsed_rows)):
                row_amt = parsed_rows[i]["amount"]
                if row_amt <= 0:
                    continue
                curr_bal = parsed_rows[i]["balance"]
                prev_bal = parsed_rows[i-1]["balance"]
                if curr_bal is not None and prev_bal is not None:
                    delta = curr_bal - prev_bal
                    if abs(delta - row_amt) < max(1.0, row_amt * 0.05):
                        parsed_rows[i]["type"] = "CREDIT"
                    elif abs(delta - (-row_amt)) < max(1.0, row_amt * 0.05):
                        parsed_rows[i]["type"] = "DEBIT"
        
    df_result = pd.DataFrame(parsed_rows)
    
    if not df_result.empty:
        # Sort by date chronologically with stable mergesort to preserve intra-day order
        df_result = df_result.sort_values(by="date", kind="mergesort").reset_index(drop=True)
        
        # If period wasn't in header, derive from date min and max
        if not header_info.get("period"):
            min_d = df_result["date"].min().strftime("%d/%m/%Y")
            max_d = df_result["date"].max().strftime("%d/%m/%Y")
            header_info["period"] = f"From {min_d} To {max_d}"

    metadata = {
        "header_info": header_info,
        "columns_detected": active_mapping,
        "available_columns": unique_headers,
        "total_raw_rows": len(df_raw),
        "parsed_rows_count": len(df_result),
        "has_balance_column": active_mapping.get("balance_col") is not None and any(r["balance"] is not None for r in parsed_rows),
        "error": None
    }
    
    return df_result, metadata
