import re
import pandas as pd
from sqlalchemy import create_engine, text
import json
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage


# ── Smart Column Generation ───────────────────────────────────────────────────
def enhance_column_names(df):
    """
    Uses the Groq LLM to detect if columns are missing or meaningless (e.g., 'Unnamed: X', or raw data).
    If so, it generates descriptive column names based on the first few rows of data.
    """
    needs_fix = False
    for c in df.columns:
        c_str = str(c).lower().strip()
        if "unnamed" in c_str or "untitled" in c_str or c_str.isdigit() or c_str.startswith("column"):
            needs_fix = True
            break

    if not needs_fix:
        return df, False

    try:
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
        # Use simple str cast for date objects etc
        sample_data = df.head(5).astype(str).to_dict(orient="records")
        current_cols = list(df.columns)
        
        system_prompt = (
            "You are a data engineering assistant. A user uploaded a dataset, but the column headers "
            "are missing or meaningless. The current parsed headers might actually be the first row of data!\n"
            "Please analyze the provided sample data and suggest short, descriptive column names (snake_case).\n\n"
            "Return ONLY a valid JSON array of strings representing the new column names, in the exact same order as the provided data columns.\n"
            "Do not include any markdown formatting aside from the JSON block, or extra text."
        )
        
        human_prompt = f"Current Parsed Columns: {current_cols}\n\nSample Data (First 5 rows):\n{json.dumps(sample_data, indent=2, default=str)}"
        
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
        response = llm.invoke(messages)
        
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        new_cols = json.loads(content)
        
        if len(new_cols) == len(df.columns):
            is_data_row = True
            for c in df.columns:
                c_str = str(c).lower().strip()
                if "unnamed" in c_str or c_str.startswith("column") or c_str.isdigit() or "untitled" in c_str:
                    is_data_row = False
                    break
            
            if is_data_row:
                push_down_row = {new_cols[i]: col_val for i, col_val in enumerate(df.columns)}
                df.columns = new_cols
                row_df = pd.DataFrame([push_down_row])
                df = pd.concat([row_df, df], ignore_index=True)
            else:
                df.columns = new_cols

            return df, True
        return df, False
    except Exception as e:
        print("LLM Column Enhancement Error:", e)
        return df, False


# ── Column Name Sanitizer ─────────────────────────────────────────────────────
def clean_column_names(df):
    """Sanitizes column names: lowercase, strip spaces, replace spaces with underscores."""
    df.columns = df.columns.astype(str).str.lower().str.strip().str.replace(" ", "_")
    return df


# ── Smart Preprocessor ────────────────────────────────────────────────────────
def preprocess_dataframe(df):
    """
    Cleans a raw DataFrame before uploading to SQL or MongoDB.
    Handles 4 common problems in messy Excel/CSV files.

    Returns:
        cleaned_df (pd.DataFrame)
        report (dict)  — summary of what was fixed (shown as UI toast)
    """
    report = {
        "junk_rows_dropped": 0,
        "date_cols_fixed": 0,
        "numeric_cols_fixed": 0,
        "nulls_filled": 0,
    }
    original_rows = len(df)

    # ── 1. Drop fully-empty rows first ───────────────────────────────────────
    df = df.dropna(how="all")

    # ── 2. Junk / Summary Row Removal ────────────────────────────────────────
    # Drop rows where ≥ 60% of values are NaN (likely empty spacer rows)
    threshold = 0.60
    row_null_pct = df.isnull().mean(axis=1)
    df = df[row_null_pct < threshold]

    # Drop rows where ANY cell contains summary keywords (case-insensitive)
    summary_keywords = ["total", "grand total", "subtotal", "sum", "average", "avg"]
    mask = pd.Series([False] * len(df), index=df.index)
    for col in df.columns:
        if df[col].dtype == object:
            str_col = df[col].astype(str).str.strip().str.lower()
            mask |= str_col.isin(summary_keywords)
    df = df[~mask]
    report["junk_rows_dropped"] = original_rows - len(df)

    # ── 3. Date Column Standardization ───────────────────────────────────────
    # Detect columns whose name hints at dates
    date_keywords = ["date", "time", "dt", "day", "month", "year", "timestamp"]
    for col in df.columns:
        if any(kw in col.lower() for kw in date_keywords):
            try:
                parsed = pd.to_datetime(df[col], infer_datetime_format=True, errors="coerce")
                # Only apply if we actually parsed some values
                if parsed.notna().sum() > 0:
                    df[col] = parsed.dt.strftime("%Y-%m-%d")
                    report["date_cols_fixed"] += 1
            except Exception:
                pass

    # ── 4. Data Type Enforcement ─────────────────────────────────────────────
    # Try to coerce object columns to numeric; keep numeric if ≥ 80% succeed
    for col in df.select_dtypes(include=["object"]).columns:
        # Skip columns that look like dates (already handled above)
        if any(kw in col.lower() for kw in date_keywords):
            continue
        numeric_attempt = pd.to_numeric(df[col], errors="coerce")
        success_rate = numeric_attempt.notna().sum() / max(len(df), 1)
        if success_rate >= 0.80:
            df[col] = numeric_attempt
            report["numeric_cols_fixed"] += 1

    # ── 5. Missing Value Fill ─────────────────────────────────────────────────
    null_count_before = df.isnull().sum().sum()
    for col in df.columns:
        if df[col].dtype in ["float64", "int64"] or pd.api.types.is_numeric_dtype(df[col]):
            # Numeric: fill with column median
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
        else:
            # Text: fill with empty string (not NaN — AI handles "" better)
            df[col] = df[col].fillna("")
    null_count_after = df.isnull().sum().sum()
    report["nulls_filled"] = int(null_count_before - null_count_after)

    return df, report


def _build_report_message(report):
    """Formats the preprocessing report into a human-readable string."""
    parts = []
    if report["junk_rows_dropped"] > 0:
        parts.append(f"🗑️ Dropped {report['junk_rows_dropped']} junk/summary row(s)")
    if report["date_cols_fixed"] > 0:
        parts.append(f"📅 Standardized {report['date_cols_fixed']} date column(s) → YYYY-MM-DD")
    if report["numeric_cols_fixed"] > 0:
        parts.append(f"🔢 Fixed {report['numeric_cols_fixed']} mixed-type column(s) → numeric")
    if report["nulls_filled"] > 0:
        parts.append(f"🩹 Filled {report['nulls_filled']} empty cell(s)")
    if report.get("columns_auto_generated"):
        parts.append("✨ AI auto-generated column names")
    return "  |  ".join(parts) if parts else "✅ Data looks clean — no issues found."


# ── SQL Upload ────────────────────────────────────────────────────────────────
def upload_file_to_sql(file_obj, db_connection_string):
    """
    Reads an Excel or CSV file, preprocesses it, and uploads it as a SQL table.
    Returns (True, table_name, report_message) or (False, error_message, "").
    """
    filename = file_obj.name
    file_ext = filename.split(".")[-1].lower()
    table_name = re.sub(r"[^a-z0-9_]", "", filename.split(".")[0].lower().strip().replace(" ", "_"))
    if not table_name:
        table_name = "uploaded_data"

    try:
        if file_ext == "csv":
            df = pd.read_csv(file_obj)
        elif file_ext in ["xlsx", "xls"]:
            df = pd.read_excel(file_obj)
        else:
            return False, "Unsupported format. Please upload CSV or Excel.", ""

        if df.empty:
            return False, "The uploaded file has no data.", ""

        # ── AI Auto-Detect Columns ───────────────────────────────────────────
        df, columns_generated = enhance_column_names(df)

        df = clean_column_names(df)

        # ── Preprocess ───────────────────────────────────────────────────────
        df, report = preprocess_dataframe(df)
        if columns_generated:
            report["columns_auto_generated"] = True
            
        report_msg = _build_report_message(report)

        engine = create_engine(db_connection_string, isolation_level="AUTOCOMMIT")
        df.to_sql(table_name, engine, if_exists="replace", index=False)

        # Verify upload
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            if count == 0 and len(df) > 0:
                return False, f"Table '{table_name}' created but has 0 rows.", ""

        return True, table_name, report_msg

    except Exception as e:
        return False, str(e), ""


# ── MongoDB Upload ────────────────────────────────────────────────────────────
def upload_file_to_mongo(file_obj, mongo_collection):
    """
    Reads an Excel/CSV, preprocesses it, and stores each row as a MongoDB document.
    Returns (True, collection_name, report_message) or (False, error_message, "").
    """
    filename = file_obj.name
    file_ext = filename.split(".")[-1].lower()

    try:
        if file_ext == "csv":
            df = pd.read_csv(file_obj)
        elif file_ext in ["xlsx", "xls"]:
            df = pd.read_excel(file_obj)
        else:
            return False, "Unsupported format. Please upload CSV or Excel.", ""

        if df.empty:
            return False, "The uploaded file has no data.", ""

        # ── AI Auto-Detect Columns ───────────────────────────────────────────
        df, columns_generated = enhance_column_names(df)

        df = clean_column_names(df)

        # ── Preprocess ───────────────────────────────────────────────────────
        df, report = preprocess_dataframe(df)
        if columns_generated:
            report["columns_auto_generated"] = True
            
        report_msg = _build_report_message(report)

        # Convert DataFrame rows → list of dicts (MongoDB documents)
        records = df.to_dict(orient="records")

        # Drop existing data to avoid duplicates on re-upload
        mongo_collection.drop()
        mongo_collection.insert_many(records)

        return True, mongo_collection.name, report_msg

    except Exception as e:
        return False, str(e), ""
