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
from sql_agent import SQLAgent
from mongo_agent import MongoAgent


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
if "user_id" not in st.session_state:          st.session_state.user_id = None
if "username" not in st.session_state:         st.session_state.username = None
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None
if "pending_unsafe_query" not in st.session_state: st.session_state.pending_unsafe_query = None


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
                        st.session_state.user_id = result
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
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.current_thread_id = None
            st.rerun()

        st.divider()
        st.subheader("💬 Threads")
        if st.button("➕ New Chat", use_container_width=True, type="primary"):
            new_thread_id = auth_mongo.create_thread(st.session_state.user_id)
            st.session_state.current_thread_id = new_thread_id
            st.rerun()

        st.subheader("Previous Chats")
        threads = auth_mongo.get_user_threads(st.session_state.user_id)
        for thread in threads:
            created_at = thread.get('created_at')
            label = created_at.strftime('%Y-%m-%d %H:%M') if created_at else "Untitled Chat"
            display_label = label[:16] + ".." if len(label) > 18 else label
            is_active = str(thread['_id']) == st.session_state.current_thread_id

            col_chat, col_del = st.columns([0.85, 0.15], gap="small")
            with col_chat:
                if st.button(display_label, key=f"thread_{thread['_id']}", use_container_width=True, disabled=is_active, help=label):
                    st.session_state.current_thread_id = str(thread['_id'])
                    st.rerun()
            with col_del:
                if st.button("🗑️", key=f"del_{thread['_id']}", use_container_width=True, help="Delete Chat"):
                    if auth_mongo.delete_thread(thread['_id']):
                        if st.session_state.current_thread_id == str(thread['_id']):
                            st.session_state.current_thread_id = None
                        st.toast("Chat deleted", icon="🗑️")
                        st.rerun()


# ── Guard: Not logged in ───────────────────────────────────────────────────────
if not st.session_state.user_id:
    st.info("👈 Please Login or Sign Up to continue.")
    st.markdown("""
### Welcome to SQLMate
The **"Upload Once, Query Forever"** AI Agent.

1. **Connect** your SQL Database (MySQL / PostgreSQL) — OR —
2. **Upload** Excel/CSV directly to MongoDB (no SQL needed!)
3. **Chat** with your data using natural language
""")
    st.stop()

if not st.session_state.current_thread_id:
    st.info("👈 Select a chat or create a new one.")
    st.stop()


# ── Load Thread State ──────────────────────────────────────────────────────────
thread_data        = auth_mongo.get_thread_details(st.session_state.current_thread_id)
current_connection = thread_data.get("decrypted_db_connection_string")   # SQL connection string (decrypted)
active_table       = thread_data.get("active_table_name")                # Active SQL table
mongo_col_name     = thread_data.get("mongo_collection_name")            # Feature 2: MongoDB collection

st.header(thread_data.get('title', 'Chat'))

# ── Connection Status Badge ────────────────────────────────────────────────────
if current_connection:
    from sqlalchemy.engine.url import make_url
    try:
        db_name = make_url(current_connection).database
    except Exception:
        db_name = "Unknown DB"
    st.caption(f"🔌 **SQL Mode** — Connected to: **{db_name}**")
    if active_table:
        st.info(f"📂 **Active Table:** `{active_table}`")
    else:
        st.caption("No specific table selected. AI will query all tables.")
    st.toast(f"Connected to SQL DB: **{db_name}**", icon="🟢")

elif mongo_col_name:
    # Feature 2: MongoDB mode active
    st.success(f"🍃 **MongoDB Mode** — Working with collection: `{mongo_col_name}`")


# ── Database Connection Section ────────────────────────────────────────────────
connection_status = "🟢 Connected" if current_connection else "🔴 Disconnected"
with st.expander(f"🔌 SQL Database Connection ({connection_status})", expanded=not current_connection):
    col1, col2 = st.columns(2)

    # ── Col 1: Connect SQL DB ──────────────────────────────────────────────────
    with col1:
        st.subheader("1. Connect SQL Database")
        conn_method = st.radio("Connect via:", ["Form (Easy)", "Raw Connection String"], horizontal=True)
        final_conn_string = None

        if conn_method == "Form (Easy)":
            st.caption("Recommended for Supabase or passwords with special characters.")
            col_h, col_p = st.columns([3, 1])
            with col_h:
                db_host = st.text_input("Host", placeholder="db.xyz.supabase.co")
            with col_p:
                db_port = st.text_input("Port", value="6543")
            db_name_form = st.text_input("Database Name", value="postgres")
            col_u, col_pwd = st.columns(2)
            with col_u:
                db_user = st.text_input("Username", value="postgres")
            with col_pwd:
                db_pass = st.text_input("Password", type="password")

            if st.button("Connect via Form"):
                if not (db_host and db_name_form and db_user and db_pass):
                    st.error("Please fill all fields.")
                else:
                    import urllib.parse
                    safe_user = urllib.parse.quote_plus(db_user)
                    safe_pass = urllib.parse.quote_plus(db_pass)
                    final_conn_string = f"postgresql://{safe_user}:{safe_pass}@{db_host}:{db_port}/{db_name_form}"

        else:
            conn_str_input = st.text_input(
                "SQL Connection String",
                value=current_connection or "",
                type="password",
                help="postgresql://user:pass@host/db"
            )
            if st.button("Connect via String"):
                final_conn_string = conn_str_input

        # ── Validate & Save Connection ─────────────────────────────────────────
        if final_conn_string:
            if "localhost" in final_conn_string or "127.0.0.1" in final_conn_string:
                st.warning("⚠️ Connecting to 'localhost'. Use a cloud DB if deployed!")
            if "supabase.co" in final_conn_string and ":5432" in final_conn_string:
                st.warning("⚠️ Supabase on port 5432 detected. Try port 6543 if this fails.")

            try:
                from sqlalchemy import create_engine, text as sa_text
                engine = create_engine(final_conn_string)
                with engine.connect() as conn:
                    conn.execute(sa_text("SELECT 1"))

                auth_mongo.update_thread_db(st.session_state.current_thread_id, final_conn_string)
                st.success("✅ Connection successful! Saved.")

                # ── Feature 1: Show all tables right after connecting ──────────
                temp_agent = SQLAgent(final_conn_string)
                table_list = temp_agent.get_table_list()
                if table_list:
                    st.subheader("📋 Tables in your Database")
                    st.dataframe(pd.DataFrame(table_list), width='stretch')
                else:
                    st.info("Connected — but no tables found yet. Upload data below.")

                time.sleep(0.5)
                st.rerun()

            except Exception as e:
                err_msg = str(e)
                if "Cannot assign requested address" in err_msg or "result too large" in err_msg.lower():
                    st.error("❌ IPv6/Network Error. Try Port 6543 (Supabase Pooler) instead of 5432.")
                else:
                    st.error(f"❌ Connection Failed: {e}")

    # ── Col 2: Upload File ─────────────────────────────────────────────────────
    with col2:
        st.subheader("2. Upload Data (Excel/CSV)")

        if current_connection:
            # SQL mode upload
            st.caption("📤 Upload to your SQL Database")
            with st.form("sql_upload_form", clear_on_submit=False):
                uploaded_file = st.file_uploader("Choose file", type=['csv', 'xlsx', 'xls'])
                if st.form_submit_button("Upload to SQL"):
                    if not uploaded_file:
                        st.warning("Please select a file to upload.")
                    else:
                        with st.spinner("Uploading to SQL..."):
                            success, result = etl_logic.upload_file_to_sql(uploaded_file, current_connection)
                            if success:
                                auth_mongo.update_thread_db(
                                    st.session_state.current_thread_id,
                                    current_connection,
                                    table_name=result
                                )
                                st.success(f"✅ Uploaded to SQL table: `{result}`")
                                auth_mongo.add_message(
                                    st.session_state.current_thread_id, "system",
                                    f"File `{uploaded_file.name}` uploaded → SQL table `{result}`."
                                )
                                st.rerun()
                            else:
                                st.error(f"Error: {result}")
        else:
            # ── Feature 2: No SQL? Upload to MongoDB ──────────────────────────
            st.caption("🍃 No SQL database? Upload to MongoDB instead!")
            st.info("Your file will be stored in our MongoDB database. The AI will query it using NoSQL (not SQL), so it works correctly for document-style data.")

            with st.form("mongo_upload_form", clear_on_submit=False):
                uploaded_file = st.file_uploader("Choose file", type=['csv', 'xlsx', 'xls'])
                if st.form_submit_button("Upload to MongoDB"):
                    if not uploaded_file:
                        st.warning("Please select a file.")
                    else:
                        with st.spinner("Uploading to MongoDB..."):
                            # Derive a safe collection name from the filename
                            import re as _re
                            col_name = _re.sub(r'[^a-z0-9_]', '', uploaded_file.name.split('.')[0].lower().replace(' ', '_'))
                            if not col_name:
                                col_name = "uploaded_data"
                            # User-specific collection to avoid data leaks between users
                            col_name = f"{st.session_state.user_id[:8]}_{col_name}"

                            mongo_collection = auth_mongo.get_db()[col_name]
                            success, result = etl_logic.upload_file_to_mongo(uploaded_file, mongo_collection)
                            if success:
                                auth_mongo.update_thread_db(
                                    st.session_state.current_thread_id,
                                    mongo_collection=result
                                )
                                st.success(f"✅ Uploaded to MongoDB collection: `{result}`")
                                auth_mongo.add_message(
                                    st.session_state.current_thread_id, "system",
                                    f"File `{uploaded_file.name}` uploaded → MongoDB collection `{result}`. AI is in NoSQL mode."
                                )
                                st.rerun()
                            else:
                                st.error(f"Error: {result}")


# ── Feature 1: View Database Schema (always visible when connected) ─────────────
if current_connection:
    with st.expander("🔍 View Database Schema"):
        try:
            temp_agent = SQLAgent(current_connection)
            schema_info = temp_agent.get_schema_info()
            st.text(schema_info)
        except Exception as e:
            st.error(f"Error fetching schema: {e}")


# ── Guard: No data source connected ───────────────────────────────────────────
if not current_connection and not mongo_col_name:
    st.warning("⚠️ No data source connected. Connect a SQL database or upload a file to MongoDB above.")
    st.stop()


# ── Initialize Agent ──────────────────────────────────────────────────────────
if current_connection:
    agent = SQLAgent(current_connection)
    mode  = "sql"
else:
    mongo_collection = auth_mongo.get_db()[mongo_col_name]
    agent = MongoAgent(mongo_collection)
    mode  = "mongo"


# ── Display Chat History ───────────────────────────────────────────────────────
messages = auth_mongo.get_messages(st.session_state.current_thread_id)
for msg in messages:
    with st.chat_message(msg['role']):
        st.markdown(msg['content'])


# ── Pending Approval (SQL Destructive Query) ────────────────────────────────────
if st.session_state.pending_unsafe_query and mode == "sql":
    st.warning("⚠️ **Potentially Destructive SQL Detected — Approval Required**")
    query_to_run = st.session_state.pending_unsafe_query['query']
    reason       = st.session_state.pending_unsafe_query['reason']
    st.code(query_to_run, language="sql")
    st.info(f"Preview of affected rows query: `{reason}`")

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


# ── Chat Input ─────────────────────────────────────────────────────────────────
if prompt := st.chat_input("Ask a question about your data..."):
    if st.session_state.pending_unsafe_query:
        st.warning("Please approve or reject the pending query above first.")
        st.stop()

    auth_mongo.add_message(st.session_state.current_thread_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        msg_placeholder = st.empty()

        if mode == "sql":
            # ── SQL Mode ───────────────────────────────────────────────────────
            schema_context = agent.get_schema_info(active_table)
            sql_query      = agent.generate_query(prompt, schema_context, active_table=active_table)

            msg_placeholder.markdown(f"**Generated SQL:**\n```sql\n{sql_query}\n```")

            is_safe, reason_or_preview = agent.check_safety(sql_query)
            if not is_safe:
                st.session_state.pending_unsafe_query = {"query": sql_query, "reason": reason_or_preview}
                auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                       f"⚠️ Destructive SQL — waiting for approval:\n```sql\n{sql_query}\n```")
                st.rerun()
            else:
                with st.spinner("Running SQL query..."):
                    success, result = agent.execute_query(sql_query)
                    if success:
                        if isinstance(result, pd.DataFrame):
                            st.dataframe(result)
                            auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                                   f"SQL: `{sql_query}`\n\nResult:\n{result.to_markdown(index=False)}")
                        else:
                            st.success(result)
                            auth_mongo.add_message(st.session_state.current_thread_id, "assistant", result)
                    else:
                        st.error(f"Error: {result}")
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Error: {result}")

        else:
            # ── MongoDB Mode (Feature 2) ────────────────────────────────────────
            schema_context  = agent.get_schema_info()
            filter_str      = agent.generate_query(prompt, schema_context)

            msg_placeholder.markdown(f"**Generated MongoDB Filter:**\n```python\n{filter_str}\n```")

            with st.spinner("Querying MongoDB..."):
                success, result = agent.execute_query(filter_str)
                if success:
                    if isinstance(result, pd.DataFrame) and not result.empty:
                        st.dataframe(result)
                        # Show row count for "how many" type questions
                        st.caption(f"📊 {len(result)} document(s) returned.")
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                               f"Filter: `{filter_str}`\n\n{len(result)} result(s):\n{result.head(20).to_markdown(index=False)}")
                    elif isinstance(result, pd.DataFrame) and result.empty:
                        st.info("No documents matched your query.")
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant",
                                               f"Filter: `{filter_str}`\n\nNo documents matched.")
                    else:
                        st.success(result)
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", str(result))
                else:
                    st.error(f"Error: {result}")
                    auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Error: {result}")
