import re
import pandas as pd
from sqlalchemy import create_engine, text


def clean_column_names(df):
    """Sanitizes column names: lowercase, strip spaces, replace spaces with underscores."""
    df.columns = df.columns.astype(str).str.lower().str.strip().str.replace(' ', '_')
    return df


def upload_file_to_sql(file_obj, db_connection_string):
    """
    Reads an Excel or CSV file and uploads it as a table to the SQL database.
    Returns (True, table_name) or (False, error_message).
    """
    filename = file_obj.name
    file_ext = filename.split('.')[-1].lower()
    table_name = re.sub(r'[^a-z0-9_]', '', filename.split('.')[0].lower().strip().replace(' ', '_'))
    if not table_name:
        table_name = "uploaded_data"

    try:
        if file_ext == 'csv':
            df = pd.read_csv(file_obj)
        elif file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_obj)
        else:
            return False, "Unsupported format. Please upload CSV or Excel."

        df = clean_column_names(df)
        if df.empty:
            return False, "The uploaded file has no data."

        engine = create_engine(db_connection_string, isolation_level="AUTOCOMMIT")
        df.to_sql(table_name, engine, if_exists='replace', index=False)

        # Verify upload
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            if count == 0 and len(df) > 0:
                return False, f"Table '{table_name}' created but has 0 rows."
        return True, table_name

    except Exception as e:
        return False, str(e)


def upload_file_to_mongo(file_obj, mongo_collection):
    """
    Feature 2: Reads an Excel/CSV and stores every row as a MongoDB document.
    Returns (True, collection_name) or (False, error_message).

    Why MongoDB?
    - The user has no SQL connection string.
    - We reuse the existing MongoDB Atlas connection — no extra infra needed.
    - Each row becomes a JSON document, which is natural for MongoDB.
    """
    filename = file_obj.name
    file_ext = filename.split('.')[-1].lower()

    try:
        if file_ext == 'csv':
            df = pd.read_csv(file_obj)
        elif file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_obj)
        else:
            return False, "Unsupported format. Please upload CSV or Excel."

        df = clean_column_names(df)
        if df.empty:
            return False, "The uploaded file has no data."

        # Convert DataFrame rows to list of dicts (MongoDB documents)
        records = df.to_dict(orient='records')

        # Drop existing data in this collection to avoid duplicates on re-upload
        mongo_collection.drop()
        mongo_collection.insert_many(records)

        return True, mongo_collection.name

    except Exception as e:
        return False, str(e)
