import pandas as pd
from sqlalchemy import create_engine, text

def clean_column_names(df):
    """
    Sanitizes column names: lowercase, strip spaces, replace spaces with underscores.
    """
    df.columns = df.columns.astype(str).str.lower().str.strip().str.replace(' ', '_')
    # Remove any non-alphanumeric chars (except underscore) if necessary
    # df.columns = df.columns.str.replace('[^a-z0-9_]', '', regex=True)
    return df

def upload_file_to_sql(file_obj, db_connection_string):
    """
    Reads an Excel or CSV file, cleans it, and uploads it to the SQL database.
    Returns the table name derived from the filename.
    """
    filename = file_obj.name
    file_ext = filename.split('.')[-1].lower()
    file_ext = filename.split('.')[-1].lower()
    table_name = filename.split('.')[0].lower().strip().replace(' ', '_')
    # Sanitize strict
    import re
    table_name = re.sub(r'[^a-z0-9_]', '', table_name)
    
    if not table_name:
        table_name = "uploaded_data"

    try:
        if file_ext == 'csv':
            df = pd.read_csv(file_obj)
        elif file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_obj)
        else:
            return False, "Unsupported file format. Please upload CSV or Excel."

        # Clean data
        df = clean_column_names(df)
        
        if df.empty:
            return False, "The uploaded file contains no data (empty rows)."

        # Create SQL Engine with AUTOCOMMIT to ensure data persists immediately
        engine = create_engine(db_connection_string, isolation_level="AUTOCOMMIT")
        
        # Upload to SQL
        # if_exists='replace' will drop the table if it exists and recreate it.
        df.to_sql(table_name, engine, if_exists='replace', index=False)
        
        # VERIFY upload immediately
        with engine.connect() as conn:
            # Check if table exists
            exists = conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{table_name}')")).scalar()
            
            # For SQLite fallback if information_schema query fails (or returns None for SQLite)
            if exists is None: 
                # Try simple select 1 limit 1
                try:
                    conn.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1"))
                    exists = True
                except:
                    exists = False
            
            if not exists:
                 return False, f"Upload appeared to succeed, but table '{table_name}' was not found in database."

            # Check row count
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            if count == 0 and len(df) > 0:
                return False, f"Table '{table_name}' created but has 0 rows (expected {len(df)})."
                
            if not table_name:
                 return False, "Internal Error: Table name is missing."
                 
            return True, table_name
        
    except Exception as e:
        return False, str(e)
