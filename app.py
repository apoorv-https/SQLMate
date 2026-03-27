import streamlit as st

# --- Page Config ---
LOGO_URL = "https://cdn-icons-png.flaticon.com/512/3067/3067260.png"
st.set_page_config(page_title="SQLMate", page_icon=LOGO_URL, layout="wide", initial_sidebar_state="expanded")

import pandas as pd
import time
from dotenv import load_dotenv
load_dotenv()

import auth_mongo
import etl_logic
from sql_agent import SQLAgent, sqlite_file_to_uri
from mongo_agent import MongoAgent
from chart_engine import detect_and_render_chart, chart_summary, _ask_llm_for_chart_config, is_chart_request


# --- Custom CSS ---
st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    .stSidebar { background-color: #262730; }
    .chat-message { padding: 1.5rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex; }
    .chat-message.user { background-color: #2b313e; }
    div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] { align-items: center !important; gap: 0px !important; }
    div[data-testid="stSidebar"] div[data-testid="column"] { display: flex; align-items: center; width: 100% !important; flex: 1 1 auto; min-width: 0; padding: 0px !important; }
    section[data-testid="stSidebar"] button { height: 38px !important; padding: 0px 5px !important; border-radius: 5px !important; margin: 2px 0px !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; display: inline-flex !important; align-items: center !important; justify-content: center !important; }
</style>
""", unsafe_allow_html=True)


# --- Session State ---
if "user_id"                not in st.session_state: st.session_state.user_id = None
if "username"               not in st.session_state: st.session_state.username = None
if "current_thread_id"      not in st.session_state: st.session_state.current_thread_id = None
if "pending_unsafe_query"   not in st.session_state: st.session_state.pending_unsafe_query = None
if "result_page"            not in st.session_state: st.session_state.result_page = 0          # Feature 9
if "last_sql_query"         not in st.session_state: st.session_state.last_sql_query = None    # Feature 7
if "title_set"              not in st.session_state: st.session_state.title_set = False        # Feature 15
# Feature 6: stores {"original_question": ..., "clarifying_q": ...} or None
if "clarification_pending"  not in st.session_state: st.session_state.clarification_pending = None

PAGE_SIZE = 100  # Feature 9: rows per page


# ── Sidebar: Auth & Navigation ─────────────────────────────────────────────────
with st.sidebar:
    st.image(LOGO_URL, width=80)
    st.title(" SQLMate")
    st.markdown("---")

    if not st.session_state.user_id:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])

        with tab1:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Login"):
                    success, result = auth_mongo.login(username, password)
                    if success:
                        st.session_state.user_id  = result
                        st.session_state.username = username
                        st.success(f"Welcome back, {username}!")
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")

        with tab2:
            with st.form("signup_form"):
                new_user = st.text_input("New Username")
                new_pass = st.text_input("New Password", type="password")
                if st.form_submit_button("Sign Up"):
                    success, result = auth_mongo.sign_up(new_user, new_pass)
                    if success:
                        st.success("Account created! Please log in.")
                    else:
                        st.error(result)

    else:
        st.write(f"Logged in as **{st.session_state.username}**")
        if st.button("Logout"):
            st.session_state.user_id           = None
            st.session_state.username          = None
            st.session_state.current_thread_id = None
            st.rerun()

        st.divider()
        st.subheader("💬 Threads")
        if st.button("➕ New Chat", use_container_width=True, type="primary"):
            new_thread_id = auth_mongo.create_thread(st.session_state.user_id)
            st.session_state.current_thread_id = new_thread_id
            st.session_state.result_page       = 0
            st.session_state.last_sql_query    = None
            st.session_state.title_set         = False
            st.session_state.clarification_pending = None
            st.rerun()

        st.subheader("Previous Chats")
        threads = auth_mongo.get_user_threads(st.session_state.user_id)
        for thread in threads:
            # Feature 15: show auto-generated title if set, else fallback to date
            title_stored = thread.get("title", "")
            if title_stored and title_stored != "New Chat":
                label = title_stored
            else:
                created_at = thread.get("created_at")
                label = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "Untitled Chat"
            display_label = label[:22] + ".." if len(label) > 24 else label
            is_active = str(thread["_id"]) == st.session_state.current_thread_id

            col_chat, col_del = st.columns([0.85, 0.15], gap="small")
            with col_chat:
                if st.button(display_label, key=f"thread_{thread['_id']}", use_container_width=True,
                             disabled=is_active, help=label):
                    st.session_state.current_thread_id = str(thread["_id"])
                    st.session_state.result_page       = 0
                    st.session_state.last_sql_query    = None
                    st.session_state.clarification_pending = None
                    st.rerun()
            with col_del:
                if st.button("🗑️", key=f"del_{thread['_id']}", use_container_width=True, help="Delete Chat"):
                    if auth_mongo.delete_thread(thread["_id"]):
                        if st.session_state.current_thread_id == str(thread["_id"]):
                            st.session_state.current_thread_id = None
                        st.toast("Chat deleted", icon="🗑️")
                        st.rerun()


# ── Guard: Not logged in ────────────────────────────────────────────────────────
if not st.session_state.user_id:
    st.info("👈 Please Login or Sign Up to continue.")
    st.markdown("""
### Welcome to SQLMate
**"Connect Once, Query Forever"** — your AI data analyst.

**Two ways to get started:**
1. 🔌 **Connect** a SQL or MongoDB database — chat with your existing data
2. 📤 **Upload** Excel/CSV — provide a SQL or MongoDB connection string to store and query it
""")
    st.stop()

if not st.session_state.current_thread_id:
    st.info("👈 Select a chat or create a new one.")
    st.stop()


# ── Load Thread State ───────────────────────────────────────────────────────────
thread_data         = auth_mongo.get_thread_details(st.session_state.current_thread_id)
current_connection  = thread_data.get("decrypted_db_connection_string")
active_table        = thread_data.get("active_table_name")
mongo_col_name      = thread_data.get("mongo_collection_name")
ext_mongo_uri       = thread_data.get("decrypted_external_mongo_uri")
ext_mongo_col       = thread_data.get("external_mongo_collection")
focused_tables      = thread_data.get("focused_tables") or []   # Feature 14

# Feature 15: sync title_set with stored title
if thread_data.get("title", "New Chat") not in ("New Chat", ""):
    st.session_state.title_set = True

st.header(thread_data.get("title", "Chat"))


# ── Connection Status Badge ─────────────────────────────────────────────────────
if current_connection:
    from sqlalchemy.engine.url import make_url
    try:
        db_name = make_url(current_connection).database
    except Exception:
        db_name = "Unknown DB"
    st.caption(f"🔌 **SQL Mode** — Connected to: **{db_name}**")
    if active_table:
        st.info(f"📂 **Active Table:** `{active_table}`")
    if focused_tables:
        st.caption(f"📌 **Focused Tables:** `{', '.join(focused_tables)}`")
    st.toast(f"Connected to SQL DB: **{db_name}**", icon="🟢")

elif ext_mongo_uri and ext_mongo_col:
    st.success(f"🍃 **Your MongoDB** — collection: `{ext_mongo_col}`")

elif mongo_col_name:
    st.success(f"🍃 **MongoDB Mode** — working with collection: `{mongo_col_name}`")


# ══════════════════════════════════════════════════════════════════════════════
# ── FLOW A: Connect to Database ───────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
sql_status   = "🟢 Connected" if current_connection else "🔴 Not connected"
mongo_status = "🟢 Connected" if (ext_mongo_uri and ext_mongo_col) else "🔴 Not connected"

with st.expander(f"🔌 Connect to a Database  |  SQL: {sql_status}  |  MongoDB: {mongo_status}",
                 expanded=not (current_connection or ext_mongo_uri)):

    conn_tab_sql, conn_tab_mongo, conn_tab_sqlite = st.tabs(["🗄️ SQL Database", "🍃 MongoDB", "📁 SQLite File"])

    # ── SQL Tab ────────────────────────────────────────────────────────────────
    with conn_tab_sql:
        st.caption("Connect to any PostgreSQL or MySQL database using a raw connection string.")
        sql_conn_input = st.text_input(
            "SQL Connection String",
            value=current_connection or "",
            type="password",
            placeholder="postgresql://user:password@host:port/dbname",
            key="sql_conn_input",
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            connect_clicked = st.button("Connect SQL", type="primary", key="btn_connect_sql", use_container_width=True)
        with col2:
            demo_clicked = st.button("✨ Try Demo Database", key="btn_demo_db", use_container_width=True)

        if demo_clicked:
            import sqlite3
            import os
            db_path = os.path.join(os.getcwd(), "demo.db").replace("\\", "/")
            if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
                with sqlite3.connect(db_path) as conn:
                    conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, department_id INTEGER, salary REAL, gender TEXT)")
                    conn.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT)")
                    conn.executemany("INSERT INTO departments VALUES (?, ?)", [(1, 'Engineering'), (2, 'Sales'), (3, 'HR')])
                    conn.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?)", [
                        (1, 'Alice', 1, 85000, 'Female'),
                        (2, 'Bob', 2, 60000, 'Male'),
                        (3, 'Charlie', 1, 120000, 'Male'),
                        (4, 'Diana', 3, 75000, 'Female'),
                        (5, 'Evan', 2, 55000, 'Male')
                    ])
            cs = f"sqlite:///{db_path}"
            auth_mongo.update_thread_db(st.session_state.current_thread_id, db_connection_string=cs)
            st.success("✅ Demo Database connected! Saved to this chat.")
            time.sleep(0.5)
            st.rerun()

        if connect_clicked:
            if not sql_conn_input.strip():
                st.error("Please enter a connection string.")
            else:
                cs = sql_conn_input.strip()
                if "localhost" in cs or "127.0.0.1" in cs:
                    st.warning("⚠️ 'localhost' detected. Use a cloud DB when deployed.")
                elif "supabase.co" in cs and ":5432" in cs:
                    st.warning("⚠️ **Supabase Port Detected (5432):** This may fail on deployed apps due to IPv4/IPv6 compatibility. We strongly recommend using the **Transaction pooler** port (`6543`) from your Supabase dashboard.")
                try:
                    from sqlalchemy import create_engine, text as sa_text
                    engine = create_engine(cs)
                    with engine.connect() as conn:
                        conn.execute(sa_text("SELECT 1"))

                    auth_mongo.update_thread_db(st.session_state.current_thread_id, db_connection_string=cs)
                    st.success("✅ SQL connection successful! Saved to this chat.")

                    temp_agent = SQLAgent(cs)
                    table_list = temp_agent.get_table_list()
                    if table_list:
                        st.subheader("📋 Tables in your Database")
                        st.dataframe(pd.DataFrame(table_list), use_container_width=True)
                    else:
                        st.info("Connected — no tables found yet. Upload a file below to create one.")

                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    err = str(e)
                    if "could not translate host name" in err or "Name or service not known" in err:
                        st.error("❌ Supabase DNS error: the direct connection host cannot be resolved.")
                        st.info(
                            "**Fix:** In your Supabase Dashboard → **Connect** → choose **Session pooler**.\n\n"
                            "Your connection string should look like:\n"
                            "```\npostgresql://postgres.<project>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres\n```\n"
                            "Port **6543** (not 5432) works on free-tier without IPv4."
                        )
                    elif "Cannot assign requested address" in err or "result too large" in err.lower():
                        st.error("❌ Network/IPv6 error. Try port 6543 instead of 5432 for Supabase.")
                    else:
                        st.error(f"❌ Connection failed: {e}")

    # ── MongoDB Tab ────────────────────────────────────────────────────────────
    with conn_tab_mongo:
        st.caption("Connect to your own MongoDB Atlas cluster using a URI and collection name.")
        ext_uri_input = st.text_input(
            "MongoDB URI",
            value=ext_mongo_uri or "",
            type="password",
            placeholder="mongodb+srv://<user>:<password>@cluster.mongodb.net/dbname",
            key="ext_mongo_uri_input",
        )
        
        if ext_uri_input.strip() and st.button("Fetch Available Collections", key="btn_fetch_mongo_cols_conn"):
            try:
                from pymongo import MongoClient as _MC
                temp_client = _MC(ext_uri_input.strip(), serverSelectionTimeoutMS=5000)
                temp_db = temp_client.get_default_database()
                cols = temp_db.list_collection_names()
                if cols:
                    st.success(f"Collections found: `{', '.join(cols)}`")
                else:
                    st.info("No collections found in this database.")
            except Exception as e:
                st.error(f"❌ Failed to fetch collections: {e}")

        ext_col_input = st.text_input(
            "Collection Name",
            value=ext_mongo_col or "",
            placeholder="my_collection",
            key="ext_mongo_col_input",
        )

        if st.button("Connect MongoDB", type="primary", key="btn_connect_mongo"):
            if not ext_uri_input.strip() or not ext_col_input.strip():
                st.error("Please enter both the MongoDB URI and a collection name.")
            else:
                try:
                    from pymongo import MongoClient as _MC
                    test_client = _MC(ext_uri_input.strip(), serverSelectionTimeoutMS=5000)
                    test_client.admin.command("ping")

                    auth_mongo.update_thread_db(
                        st.session_state.current_thread_id,
                        external_mongo_uri=ext_uri_input.strip(),
                        external_mongo_collection=ext_col_input.strip(),
                    )
                    st.success(f"✅ Connected to your MongoDB — collection: `{ext_col_input.strip()}`")

                    ext_col_obj = test_client.get_default_database()[ext_col_input.strip()]
                    samples = list(ext_col_obj.find({}, {"_id": 0}).limit(3))
                    if samples:
                        st.subheader("🔍 Sample Data from Collection")
                        st.dataframe(pd.DataFrame(samples), use_container_width=True)
                        st.caption(f"Fields: `{', '.join(samples[0].keys())}`")
                    else:
                        st.info("Collection is empty. Upload a file below to populate it.")

                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ MongoDB connection failed: {e}")

    # ── Feature 12: SQLite File Upload Tab ─────────────────────────────────────
    with conn_tab_sqlite:
        st.caption("Upload a `.db` or `.sqlite` file — no server required.")
        sqlite_file = st.file_uploader("Choose SQLite file", type=["db", "sqlite", "sqlite3"],
                                       key="sqlite_upload")
        if st.button("Load SQLite File", type="primary", key="btn_load_sqlite"):
            if not sqlite_file:
                st.error("Please select a .db / .sqlite file.")
            else:
                try:
                    sqlite_uri = sqlite_file_to_uri(sqlite_file)
                    temp_agent = SQLAgent(sqlite_uri)
                    table_list = temp_agent.get_table_list()

                    auth_mongo.update_thread_db(
                        st.session_state.current_thread_id,
                        db_connection_string=sqlite_uri,
                    )
                    st.success(f"✅ SQLite file loaded! Found {len(table_list)} table(s).")
                    if table_list:
                        st.dataframe(pd.DataFrame(table_list), use_container_width=True)
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed to load SQLite file: {e}")


# ── SQL Schema Viewer + Feature 13 ER Diagram + Feature 14 Multi-table ─────────
if current_connection:
    temp_agent = SQLAgent(current_connection)
    all_tables = [t["Table"] for t in temp_agent.get_table_list()]

    # Feature 14: Multi-table selector
    with st.expander("📌 Select Focused Tables (multi-table context)", expanded=False):
        st.caption("Choose which tables the AI should know about. Leave empty to include ALL tables.")
        chosen = st.multiselect(
            "Tables in scope:",
            options=all_tables,
            default=focused_tables if focused_tables else all_tables,
            key="table_selector",
        )
        if st.button("Save Table Selection", key="btn_save_tables"):
            auth_mongo.update_thread_db(
                st.session_state.current_thread_id,
                focused_tables=chosen if chosen != all_tables else [],
            )
            st.success("✅ Table selection saved.")
            st.rerun()

    # Schema viewer
    with st.expander("🔍 View SQL Schema (with FK relationships)"):
        schema_info = temp_agent.get_schema_info(focused_tables=focused_tables or None)
        st.text(schema_info)

    # (ER Diagram feature removed by user request)


# ══════════════════════════════════════════════════════════════════════════════
# ── FLOW B: Upload Excel / CSV ────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("📤 Upload Excel / CSV File", expanded=False):
    st.info(
        "Upload a file to store it in a database, then chat with it. "
        "You must choose where to store the file: SQL or MongoDB."
    )

    uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx", "xls"], key="upload_file")
    store_in      = st.radio("Store in:", ["SQL Database", "MongoDB"], horizontal=True, key="upload_dest")

    if store_in == "SQL Database":
        upload_sql_conn = st.text_input(
            "SQL Connection String",
            type="password",
            placeholder="postgresql://user:password@host:port/dbname",
            key="upload_sql_conn",
            help="The uploaded file will be created as a table in this SQL database.",
        )
        upload_mongo_uri = None
        upload_mongo_col = None
    else:
        upload_mongo_uri = st.text_input(
            "MongoDB URI",
            type="password",
            placeholder="mongodb+srv://<user>:<password>@cluster.mongodb.net/dbname",
            key="upload_mongo_uri",
        )
        
        if upload_mongo_uri.strip() and st.button("Fetch Available Collections", key="btn_fetch_mongo_cols_upload"):
            try:
                from pymongo import MongoClient as _MC
                temp_client = _MC(upload_mongo_uri.strip(), serverSelectionTimeoutMS=5000)
                temp_db = temp_client.get_default_database()
                cols = temp_db.list_collection_names()
                if cols:
                    st.success(f"Collections found: `{', '.join(cols)}`")
                else:
                    st.info("No collections found in this database.")
            except Exception as e:
                st.error(f"❌ Failed to fetch collections: {e}")

        upload_mongo_col = st.text_input(
            "Collection Name",
            placeholder="my_collection",
            key="upload_mongo_col",
        )
        upload_sql_conn = None

    if st.button("⚡ Upload & Process", type="primary", key="btn_upload"):
        if not uploaded_file:
            st.warning("Please select a file.")
        elif store_in == "SQL Database" and not upload_sql_conn:
            st.error("Please enter your SQL connection string.")
        elif store_in == "MongoDB" and (not upload_mongo_uri or not upload_mongo_col):
            st.error("Please enter both your MongoDB URI and collection name.")
        else:
            with st.spinner("Uploading and cleaning your data..."):

                if store_in == "SQL Database":
                    cs = upload_sql_conn.strip()
                    if "supabase.co" in cs and ":5432" in cs:
                        st.warning("⚠️ **Supabase Port Detected (5432):** This may fail on deployed apps due to IPv4/IPv6 compatibility. Please use the **Transaction pooler** port (`6543`).")
                    success, result, report_msg = etl_logic.upload_file_to_sql(uploaded_file, cs)
                    if success:
                        auth_mongo.update_thread_db(
                            st.session_state.current_thread_id,
                            db_connection_string=cs,
                            table_name=result,
                        )
                        st.success(f"✅ Uploaded to SQL table: `{result}`")
                        if report_msg:
                            st.toast(f"🧹 ETL: {report_msg}", icon="✨")
                        auth_mongo.add_message(
                            st.session_state.current_thread_id, "system",
                            f"File `{uploaded_file.name}` uploaded → SQL table `{result}`. ETL: {report_msg}",
                        )
                        st.rerun()
                    else:
                        st.error(f"❌ {result}")

                else:  # MongoDB
                    try:
                        from pymongo import MongoClient as _MC
                        ext_client = _MC(upload_mongo_uri.strip(), serverSelectionTimeoutMS=5000)
                        ext_client.admin.command("ping")
                        ext_col_obj = ext_client.get_default_database()[upload_mongo_col.strip()]

                        success, result, report_msg = etl_logic.upload_file_to_mongo(uploaded_file, ext_col_obj)
                        if success:
                            auth_mongo.update_thread_db(
                                st.session_state.current_thread_id,
                                external_mongo_uri=upload_mongo_uri.strip(),
                                external_mongo_collection=result,
                            )
                            st.success(f"✅ Uploaded to MongoDB collection: `{result}`")
                            if report_msg:
                                st.toast(f"🧹 ETL: {report_msg}", icon="✨")
                            auth_mongo.add_message(
                                st.session_state.current_thread_id, "system",
                                f"File `{uploaded_file.name}` uploaded → MongoDB collection `{result}`. ETL: {report_msg}",
                            )
                            st.rerun()
                        else:
                            st.error(f"❌ {result}")
                    except Exception as e:
                        st.error(f"❌ MongoDB connection failed: {e}")


# ── Guard: No data source ────────────────────────────────────────────────────────
if not current_connection and not mongo_col_name and not (ext_mongo_uri and ext_mongo_col):
    st.warning("⚠️ No data source connected yet. Use the sections above to connect or upload.")
    st.stop()


# ── Initialize Agent ──────────────────────────────────────────────────────────────
if current_connection:
    agent = SQLAgent(current_connection)
    mode  = "sql"

elif ext_mongo_uri and ext_mongo_col:
    from pymongo import MongoClient as _MC
    _ext_client = _MC(ext_mongo_uri, serverSelectionTimeoutMS=5000)
    _ext_col    = _ext_client.get_default_database()[ext_mongo_col]
    agent = MongoAgent(_ext_col)
    mode  = "ext_mongo"

else:
    mongo_collection = auth_mongo.get_db()[mongo_col_name]
    agent = MongoAgent(mongo_collection)
    mode  = "mongo"


# ── Helper: paginated DataFrame display (Feature 9) ──────────────────────────────
def show_paginated_df(df, key_prefix="page"):
    """Shows a DataFrame with Prev/Next pagination (PAGE_SIZE rows per page)."""
    total_rows = len(df)
    total_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
    page = st.session_state.result_page

    # Clamp page
    page = max(0, min(page, total_pages - 1))
    st.session_state.result_page = page

    start = page * PAGE_SIZE
    end   = min(start + PAGE_SIZE, total_rows)
    st.dataframe(df.iloc[start:end], use_container_width=True)

    if total_pages > 1:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            if st.button("⬅️ Prev", key=f"{key_prefix}_prev", disabled=(page == 0)):
                st.session_state.result_page = page - 1
                st.rerun()
        with c2:
            st.caption(f"Page {page + 1} of {total_pages}  ({total_rows} rows total)")
        with c3:
            if st.button("Next ➡️", key=f"{key_prefix}_next", disabled=(page == total_pages - 1)):
                st.session_state.result_page = page + 1
                st.rerun()


# ── Display Chat History ───────────────────────────────────────────────────────────
messages = auth_mongo.get_messages(st.session_state.current_thread_id)
for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# ── Pending Approval (Destructive Operation) ──────────────────────────────────────
if st.session_state.pending_unsafe_query:
    st.warning("⚠️ **Potentially Destructive Operation Detected — Approval Required**")
    query_to_run = st.session_state.pending_unsafe_query["query"]
    reason       = st.session_state.pending_unsafe_query["reason"]
    lang         = "sql" if mode == "sql" else "json"
    st.code(query_to_run, language=lang)
    st.info(f"Preview query: `{reason}`")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Yes, Execute", type="primary", use_container_width=True):
            with st.spinner("Executing..."):
                success, result = agent.execute_query(query_to_run)
                if success:
                    if isinstance(result, pd.DataFrame):
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                               f"Approved & Executed: `{query_to_run}`\n\n{result.to_markdown(index=False)}")
                    else:
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", result)
                else:
                    auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Error: {result}")
            st.session_state.pending_unsafe_query = None
            st.rerun()
    with c2:
        if st.button("❌ Cancel", use_container_width=True):
            auth_mongo.add_message(st.session_state.current_thread_id, "assistant", "Action cancelled by user.")
            st.session_state.pending_unsafe_query = None
            st.rerun()


# ── Feature 6: Show pending clarification question ───────────────────────────────
# Guard: if old sessions stored a plain string, reset to None
if isinstance(st.session_state.clarification_pending, str):
    st.session_state.clarification_pending = None
if st.session_state.clarification_pending:
    clarif_q = st.session_state.clarification_pending.get("clarifying_q", "")
    st.info(f"🤔 **Before I generate a query:** {clarif_q}")


# ── Chat Input ─────────────────────────────────────────────────────────────────────
if prompt := st.chat_input("Ask a question about your data, or ask to draw a chart..."):
    if st.session_state.pending_unsafe_query:
        st.warning("Please approve or reject the pending query above first.")
        st.stop()

    auth_mongo.add_message(st.session_state.current_thread_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # ── Feature 7: Detect refinement intent ─────────────────────────────────
    REFINEMENT_TRIGGERS = ["only", "top ", "limit ", "filter ", "add where", "sort by",
                           "order by", "just show", "refine", "also", "now also", "group by"]
    is_refinement = (
        st.session_state.last_sql_query is not None and
        mode == "sql" and
        any(t in prompt.lower() for t in REFINEMENT_TRIGGERS)
    )

    # ── Feature 15: Auto-name thread on first user message ───────────────────
    if not st.session_state.title_set and mode == "sql":
        try:
            title = agent.generate_thread_title(prompt)
            auth_mongo.update_thread_title(st.session_state.current_thread_id, title)
            st.session_state.title_set = True
        except Exception:
            pass

    with st.chat_message("assistant"):
        msg_placeholder = st.empty()

        # ══════════════════════════════════════════════════════════════════════
        # ── SQL MODE ──────────────────────────────────────────────────────────
        # ══════════════════════════════════════════════════════════════════════
        if mode == "sql":
            schema_context = agent.get_schema_info(focused_tables=focused_tables or None)

            # Build recent chat history window (last 10 user/assistant turns) for LLM memory
            all_msgs = auth_mongo.get_messages(st.session_state.current_thread_id)
            history_window = [
                {"role": m["role"], "content": m["content"]}
                for m in all_msgs
                if m["role"] in ("user", "assistant")
            ][-10:]

            # Feature 6: If a clarification was pending, combine original Q + clarif + answer
            if st.session_state.clarification_pending:
                orig_q   = st.session_state.clarification_pending.get("original_question", "")
                clarif_q = st.session_state.clarification_pending.get("clarifying_q", "")
                # Build a single enriched question that gives LLM full context
                effective_prompt = (
                    f"{orig_q}\n\n"
                    f"[Clarification asked: {clarif_q}]\n"
                    f"[User answered: {prompt}]"
                )
                st.session_state.clarification_pending = None   # resolved
                skip_clarif_check = True
            else:
                effective_prompt = prompt
                skip_clarif_check = False

            # Feature 6: Ambiguity check (skip if refinement or already clarified)
            if not is_refinement and not skip_clarif_check:
                needs_clarif, clarif_q = agent.needs_clarification(
                    effective_prompt, schema_context, chat_history=history_window
                )
                if needs_clarif:
                    st.session_state.clarification_pending = {
                        "original_question": prompt,
                        "clarifying_q": clarif_q,
                    }
                    clarif_msg = f"🤔 **Could you clarify?** {clarif_q}"
                    msg_placeholder.markdown(clarif_msg)
                    auth_mongo.add_message(st.session_state.current_thread_id, "assistant", clarif_msg)
                    st.rerun()

            # Feature 7: Refinement vs fresh query
            if is_refinement and st.session_state.last_sql_query:
                sql_query = agent.refine_query(
                    st.session_state.last_sql_query, effective_prompt, schema_context,
                    chat_history=history_window
                )
                msg_placeholder.markdown(f"**🔄 Refined SQL:**\n```sql\n{sql_query}\n```")
            else:
                sql_query = agent.generate_query(
                    effective_prompt, schema_context,
                    active_table=active_table,
                    focused_tables=focused_tables or None,
                    chat_history=history_window
                )
                msg_placeholder.markdown(f"**Generated SQL:**\n```sql\n{sql_query}\n```")


            # Feature 5: Inline explanation (collapsible)
            with st.expander("💡 What does this query do?", expanded=False):
                explanation = agent.explain_query(sql_query)
                st.markdown(explanation)

            is_safe, reason_or_preview = agent.check_safety(sql_query)
            if not is_safe:
                st.session_state.pending_unsafe_query = {"query": sql_query, "reason": reason_or_preview}
                auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                       f"⚠️ Destructive SQL — waiting for approval:\n```sql\n{sql_query}\n```")
                st.rerun()
            else:
                with st.spinner("Running query..."):
                    success, result = agent.execute_query(sql_query)

                    # Feature 3: Auto-retry on error
                    if not success:
                        st.warning(f"⚠️ Query failed: `{result}` — retrying with correction…")
                        sql_query = agent.generate_query_with_retry(
                            prompt, schema_context, sql_query, result, active_table=active_table
                        )
                        msg_placeholder.markdown(f"**🔁 Corrected SQL:**\n```sql\n{sql_query}\n```")
                        success, result = agent.execute_query(sql_query)

                    st.session_state.last_sql_query = sql_query  # Feature 7: track for refinement

                    if success:
                        if isinstance(result, pd.DataFrame) and not result.empty:
                            st.session_state.result_page = 0  # reset page on new result
                            chart_shown = detect_and_render_chart(effective_prompt, result, st)
                            if not chart_shown:
                                show_paginated_df(result)   # Feature 9
                            config = _ask_llm_for_chart_config(effective_prompt, list(result.columns)) if is_chart_request(effective_prompt) else None
                            save_msg = (
                                f"SQL: `{sql_query}`\n\n{chart_summary(config) if chart_shown else ''}"
                                f"\n\n{result.head(20).to_markdown(index=False)}"
                            )
                            auth_mongo.add_message(st.session_state.current_thread_id, "assistant", save_msg.strip())
                        elif isinstance(result, pd.DataFrame) and result.empty:
                            st.info("Query returned no rows.")
                            auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                                   f"SQL: `{sql_query}`\n\nNo rows returned.")
                        else:
                            st.success(result)
                            auth_mongo.add_message(st.session_state.current_thread_id, "assistant", result)
                    else:
                        st.error(f"Error after retry: {result}")
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                               f"Error after retry: {result}")

        # ══════════════════════════════════════════════════════════════════════
        # ── MONGODB MODE ──────────────────────────────────────────────────────
        # ══════════════════════════════════════════════════════════════════════
        else:
            schema_context = agent.get_schema_info()

            # Build recent chat history window (last 10 user/assistant turns) for LLM memory
            all_msgs_mongo = auth_mongo.get_messages(st.session_state.current_thread_id)
            history_window_mongo = [
                {"role": m["role"], "content": m["content"]}
                for m in all_msgs_mongo
                if m["role"] in ("user", "assistant")
            ][-10:]

            # Feature 6: If a clarification was pending, combine original Q + clarif + answer
            if st.session_state.clarification_pending:
                orig_q   = st.session_state.clarification_pending.get("original_question", "")
                clarif_q = st.session_state.clarification_pending.get("clarifying_q", "")
                effective_prompt_mongo = (
                    f"{orig_q}\n\n"
                    f"[Clarification asked: {clarif_q}]\n"
                    f"[User answered: {prompt}]"
                )
                st.session_state.clarification_pending = None
                skip_clarif_mongo = True
            else:
                effective_prompt_mongo = prompt
                skip_clarif_mongo = False

            # Feature 6: Ambiguity check (skip if refinement or already clarified)
            REFINEMENT_TRIGGERS_MONGO = ["only", "top ", "limit ", "filter ", "sort by",
                                         "order by", "just show", "refine", "also", "group by"]
            is_refinement_mongo = (
                st.session_state.last_sql_query is not None and
                any(t in prompt.lower() for t in REFINEMENT_TRIGGERS_MONGO)
            )
            if not is_refinement_mongo and not skip_clarif_mongo:
                needs_clarif, clarif_q = agent.needs_clarification(
                    effective_prompt_mongo, schema_context, chat_history=history_window_mongo
                )
                if needs_clarif:
                    st.session_state.clarification_pending = {
                        "original_question": prompt,
                        "clarifying_q": clarif_q,
                    }
                    clarif_msg = f"🤔 **Could you clarify?** {clarif_q}"
                    msg_placeholder.markdown(clarif_msg)
                    auth_mongo.add_message(st.session_state.current_thread_id, "assistant", clarif_msg)
                    st.rerun()

            # Feature 15: Thread auto-naming on first message
            if not st.session_state.title_set:
                try:
                    title = agent.generate_thread_title(prompt)
                    auth_mongo.update_thread_title(st.session_state.current_thread_id, title)
                    st.session_state.title_set = True
                except Exception:
                    pass

            # Feature 7: Refinement vs fresh operation
            if is_refinement_mongo and st.session_state.last_sql_query:
                operation_str = agent.refine_query(
                    st.session_state.last_sql_query, effective_prompt_mongo, schema_context,
                    chat_history=history_window_mongo
                )
                op_label = "🔄 Refined MongoDB Operation"
            else:
                operation_str = agent.generate_query(
                    effective_prompt_mongo, schema_context,
                    chat_history=history_window_mongo
                )
                try:
                    import json as _json
                    _op = _json.loads(operation_str).get("operation", "find")
                except Exception:
                    _op = "find"
                op_label = "MongoDB Operation" if _op != "find" else "MongoDB Filter"

            msg_placeholder.markdown(f"**Generated {op_label}:**\n```json\n{operation_str}\n```")

            # Feature 5: Inline explanation
            with st.expander("💡 What does this operation do?", expanded=False):
                explanation = agent.explain_query(operation_str)
                st.markdown(explanation)

            is_safe, reason_or_preview = agent.check_safety(operation_str)
            if not is_safe:
                st.session_state.pending_unsafe_query = {"query": operation_str, "reason": reason_or_preview}
                auth_mongo.add_message(
                    st.session_state.current_thread_id, "assistant",
                    f"⚠️ Destructive MongoDB operation — waiting for approval:\n```json\n{operation_str}\n```",
                )
                st.rerun()

            with st.spinner("Running MongoDB operation..."):
                success, result = agent.execute_query(operation_str)

                # Feature 3: Auto-retry on error
                if not success:
                    st.warning(f"⚠️ Operation failed: `{result}` — retrying with correction…")
                    operation_str = agent.generate_query_with_retry(
                        effective_prompt_mongo, schema_context, operation_str, result,
                        chat_history=history_window_mongo
                    )
                    msg_placeholder.markdown(f"**🔁 Corrected Operation:**\n```json\n{operation_str}\n```")
                    success, result = agent.execute_query(operation_str)

                st.session_state.last_sql_query = operation_str  # Feature 7: track for refinement

                if success:
                    if isinstance(result, pd.DataFrame) and not result.empty:
                        st.session_state.result_page = 0
                        chart_shown = detect_and_render_chart(effective_prompt_mongo, result, st)
                        if not chart_shown:
                            show_paginated_df(result)   # Feature 9
                        st.caption(f"📊 {len(result)} document(s) returned.")
                        config = _ask_llm_for_chart_config(effective_prompt_mongo, list(result.columns)) if is_chart_request(effective_prompt_mongo) else None
                        save_msg = (
                            f"Operation: `{operation_str}`\n\n{chart_summary(config) if chart_shown else ''}"
                            f"\n\n{len(result)} result(s):\n{result.head(20).to_markdown(index=False)}"
                        )
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", save_msg.strip())
                    elif isinstance(result, pd.DataFrame) and result.empty:
                        st.info("No documents matched your query.")
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                               f"Operation: `{operation_str}`\n\nNo documents matched.")
                    else:
                        st.success(result)
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", str(result))
                else:
                    st.error(f"Error after retry: {result}")
                    auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                           f"Error after retry: {result}")

