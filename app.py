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
            st.rerun()

        st.subheader("Previous Chats")
        threads = auth_mongo.get_user_threads(st.session_state.user_id)
        for thread in threads:
            created_at  = thread.get("created_at")
            label       = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "Untitled Chat"
            display_label = label[:16] + ".." if len(label) > 18 else label
            is_active   = str(thread["_id"]) == st.session_state.current_thread_id

            col_chat, col_del = st.columns([0.85, 0.15], gap="small")
            with col_chat:
                if st.button(display_label, key=f"thread_{thread['_id']}", use_container_width=True, disabled=is_active, help=label):
                    st.session_state.current_thread_id = str(thread["_id"])
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
thread_data      = auth_mongo.get_thread_details(st.session_state.current_thread_id)
current_connection  = thread_data.get("decrypted_db_connection_string")     # SQL URI
active_table        = thread_data.get("active_table_name")                   # SQL focused table
mongo_col_name      = thread_data.get("mongo_collection_name")               # Internal Atlas collection
ext_mongo_uri       = thread_data.get("decrypted_external_mongo_uri")        # User's own MongoDB URI [NEW]
ext_mongo_col       = thread_data.get("external_mongo_collection")           # Collection in user's Atlas [NEW]

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
    st.toast(f"Connected to SQL DB: **{db_name}**", icon="🟢")

elif ext_mongo_uri and ext_mongo_col:
    st.success(f"🍃 **Your MongoDB** — collection: `{ext_mongo_col}`")

elif mongo_col_name:
    st.success(f"🍃 **MongoDB Mode** — working with collection: `{mongo_col_name}`")


# ══════════════════════════════════════════════════════════════════════════════
# ── FLOW A: Connect to Database (no file needed) ──────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
sql_status = "🟢 Connected" if current_connection else "🔴 Not connected"
mongo_status = "🟢 Connected" if (ext_mongo_uri and ext_mongo_col) else "🔴 Not connected"

with st.expander(f"🔌 Connect to a Database  |  SQL: {sql_status}  |  MongoDB: {mongo_status}", expanded=not (current_connection or ext_mongo_uri)):

    conn_tab_sql, conn_tab_mongo = st.tabs(["🗄️ SQL Database", "🍃 MongoDB"])

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

        if st.button("Connect SQL", type="primary", key="btn_connect_sql"):
            if not sql_conn_input.strip():
                st.error("Please enter a connection string.")
            else:
                cs = sql_conn_input.strip()
                if "localhost" in cs or "127.0.0.1" in cs:
                    st.warning("⚠️ 'localhost' detected. Use a cloud DB when deployed.")
                try:
                    from sqlalchemy import create_engine, text as sa_text
                    engine = create_engine(cs)
                    with engine.connect() as conn:
                        conn.execute(sa_text("SELECT 1"))

                    auth_mongo.update_thread_db(st.session_state.current_thread_id, db_connection_string=cs)
                    st.success("✅ SQL connection successful! Saved to this chat.")

                    # Show all tables right after connecting
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
                    if "Cannot assign requested address" in err or "result too large" in err.lower():
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

                    # Save to thread (URI encrypted, collection plain)
                    auth_mongo.update_thread_db(
                        st.session_state.current_thread_id,
                        external_mongo_uri=ext_uri_input.strip(),
                        external_mongo_collection=ext_col_input.strip(),
                    )
                    st.success(f"✅ Connected to your MongoDB — collection: `{ext_col_input.strip()}`")

                    # Show sample documents & fields
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


# ── View SQL Schema (always visible when SQL connected) ─────────────────────────
if current_connection:
    with st.expander("🔍 View SQL Database Schema"):
        try:
            temp_agent  = SQLAgent(current_connection)
            schema_info = temp_agent.get_schema_info()
            st.text(schema_info)
        except Exception as e:
            st.error(f"Error fetching schema: {e}")


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
                    success, result, report_msg = etl_logic.upload_file_to_sql(uploaded_file, cs)
                    if success:
                        # Save SQL connection + active table to the thread
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


# ── Guard: No data source connected ─────────────────────────────────────────────
if not current_connection and not mongo_col_name and not (ext_mongo_uri and ext_mongo_col):
    st.warning("⚠️ No data source connected yet. Use the sections above to connect or upload.")
    st.stop()


# ── Initialize Agent ─────────────────────────────────────────────────────────────
if current_connection:
    agent = SQLAgent(current_connection)
    mode  = "sql"

elif ext_mongo_uri and ext_mongo_col:
    # User's own MongoDB cluster
    from pymongo import MongoClient as _MC
    _ext_client = _MC(ext_mongo_uri, serverSelectionTimeoutMS=5000)
    _ext_col    = _ext_client.get_default_database()[ext_mongo_col]
    agent = MongoAgent(_ext_col)
    mode  = "ext_mongo"

else:
    # Internal Atlas collection (file uploaded without SQL or external Mongo)
    mongo_collection = auth_mongo.get_db()[mongo_col_name]
    agent = MongoAgent(mongo_collection)
    mode  = "mongo"


# ── Display Chat History ──────────────────────────────────────────────────────────
messages = auth_mongo.get_messages(st.session_state.current_thread_id)
for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# ── Pending Approval (Destructive Operation — SQL or MongoDB) ─────────────────────
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


# ── Chat Input ────────────────────────────────────────────────────────────────────
if prompt := st.chat_input("Ask a question about your data, or ask to draw a chart..."):
    if st.session_state.pending_unsafe_query:
        st.warning("Please approve or reject the pending query above first.")
        st.stop()

    auth_mongo.add_message(st.session_state.current_thread_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        msg_placeholder = st.empty()

        # ── SQL Mode ────────────────────────────────────────────────────────────
        if mode == "sql":
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
                with st.spinner("Running query..."):
                    success, result = agent.execute_query(sql_query)
                    if success:
                        if isinstance(result, pd.DataFrame) and not result.empty:
                            # ── Chart or Table ──────────────────────────────
                            config      = _ask_llm_for_chart_config(prompt, list(result.columns)) if is_chart_request(prompt) else None
                            chart_shown = detect_and_render_chart(prompt, result, st)
                            if not chart_shown:
                                st.dataframe(result)
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
                        st.error(f"Error: {result}")
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Error: {result}")

        # ── MongoDB Mode (internal Atlas OR user's own) ─────────────────────────
        else:
            schema_context = agent.get_schema_info()
            operation_str  = agent.generate_query(prompt, schema_context)

            # Detect operation type for display label
            try:
                import json as _json
                _op = _json.loads(operation_str).get("operation", "find")
            except Exception:
                _op = "find"
            op_label = "MongoDB Operation" if _op != "find" else "MongoDB Filter"
            msg_placeholder.markdown(f"**Generated {op_label}:**\n```json\n{operation_str}\n```")

            # ── Safety Check (mirrors SQL mode) ──────────────────────────────
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
                if success:
                    if isinstance(result, pd.DataFrame) and not result.empty:
                        # ── Chart or Table ──────────────────────────────────
                        config      = _ask_llm_for_chart_config(prompt, list(result.columns)) if is_chart_request(prompt) else None
                        chart_shown = detect_and_render_chart(prompt, result, st)
                        if not chart_shown:
                            st.dataframe(result)
                        st.caption(f"📊 {len(result)} document(s) returned.")
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
                    st.error(f"Error: {result}")
                    auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Error: {result}")
