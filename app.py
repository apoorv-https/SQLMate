import streamlit as st
import pandas as pd
import time
from dotenv import load_dotenv
load_dotenv()
import auth_mongo
import etl_logic
from sql_agent import SQLAgent

# --- Page Config ---
st.set_page_config(
    page_title="SQLMate",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for Dark Mode & Styling ---
st.markdown("""
<style>
    /* Global Dark Mode adjustments if needed, though Streamlit handles most */
    .stApp {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    .stSidebar {
        background-color: #262730;
    }
    /* Chat Message Styling */
    .chat-message {
        padding: 1.5rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        display: flex;
    } 
    .chat-message.user {
        background-color: #2b313e;
    }
    /* Fix sidebar button alignment - Force flex row and center */
    div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
        align-items: center !important;
        gap: 0px !important; /* Remove gap */
    }
    
    /* Column adjustments */
    div[data-testid="stSidebar"] div[data-testid="column"] {
        display: flex;
        align-items: center;
        width: 100% !important;
        flex: 1 1 auto;
        min-width: 0;
        padding: 0px !important;
    }
    
    /* Button Styling */
    section[data-testid="stSidebar"] button {
        height: 38px !important; /* Slightly smaller height */
        padding: 0px 5px !important; /* Minimal padding */
        border-radius: 5px !important;
        margin: 2px 0px !important; /* Vertical spacing */
        line-height: 1.2 !important;
        
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Session State Initialization ---
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = None
if "current_thread_id" not in st.session_state:
    st.session_state.current_thread_id = None

# --- Sidebar: Auth & Navigation ---
with st.sidebar:
    st.title("🤖 SQLMate")
    st.markdown("---")
    
    if not st.session_state.user_id:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        
        with tab1:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submit_login = st.form_submit_button("Login")
                
                if submit_login:
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
                submit_signup = st.form_submit_button("Sign Up")
                
                if submit_signup:
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
        
        # Thread Management
        st.subheader("💬 Threads")
        if st.button("➕ New Chat", use_container_width=True, type="primary"):
            new_thread_id = auth_mongo.create_thread(st.session_state.user_id)
            st.session_state.current_thread_id = new_thread_id
            st.rerun()
            
        st.subheader("Previous Chats")
        threads = auth_mongo.get_user_threads(st.session_state.user_id)
        
        for thread in threads:
            # Format label: "📅 YYYY-MM-DD HH:MM"
            created_at = thread.get('created_at')
            if created_at:
                label = created_at.strftime('%Y-%m-%d %H:%M')
            else:
                label = "Untitled Chat"
                
            # Highlight current thread
            is_active = str(thread['_id']) == st.session_state.current_thread_id
            
            # Truncate label if too long for sidebar
            if len(label) > 18:
                display_label = label[:16] + ".."
            else:
                display_label = label
                
            # Use columns for layout: [Chat Button] [Delete Button]
            col_chat, col_del = st.columns([0.85, 0.15], gap="small")
            
            with col_chat:
                if st.button(display_label, key=f"thread_{thread['_id']}", use_container_width=True, disabled=is_active, help=label):
                    st.session_state.current_thread_id = str(thread['_id'])
                    st.rerun()
            
            with col_del:
                if st.button("🗑️", key=f"del_{thread['_id']}", use_container_width=True, help="Delete Chat"):
                    if auth_mongo.delete_thread(thread['_id']):
                        # If we deleted the active thread, reset current_thread_id
                        if st.session_state.current_thread_id == str(thread['_id']):
                            st.session_state.current_thread_id = None
                        st.toast("Chat deleted", icon="🗑️")
                        st.rerun()


# --- Main Interface ---
if not st.session_state.user_id:
    st.info("👈 Please Login or Sign Up to continue.")
    st.markdown("""
    ### Welcome to Sentient SQL
    The **"Upload Once, Query Forever"** AI Agent.
    
    1.  **Connect** your Database (MySQL/Postgres)
    2.  **Upload** Excel/CSV files directly to your SQL DB
    3.  **Chat** with your data using natural language
    """)
    st.stop()

# Load Current Thread Context
if not st.session_state.current_thread_id:
    st.info("👈 Select a chat or create a new one.")
    st.stop()
    
thread_data = auth_mongo.get_thread_details(st.session_state.current_thread_id)
current_connection = thread_data.get("decrypted_db_connection_string")
active_table = thread_data.get("active_table_name")

st.header(thread_data.get('title', 'Chat'))

if not current_connection:
    st.info("ℹ️ No database connected to this chat yet. Please connect one below.")
else:
    # Extract DB name for user verification
    from sqlalchemy.engine.url import make_url
    try:
        db_name = make_url(current_connection).database
    except:
        db_name = "Unknown DB"
        
    st.caption(f"🔌 Connected to: **{db_name}**")
    
    if active_table:
        st.info(f"📂 **Active Table:** `{active_table}`")
        # Ensure agent knows this is the priority table
    else:
        st.caption("No specific table selected. AI will look at all tables.")
    # Small indicator that we are connected
    st.toast(f"Connected to Database: **{db_name}**", icon="🟢")


# --- Data Ingestion Section ---
connection_status = "🟢 Connected" if current_connection else "🔴 Disconnected"
with st.expander(f"🔌 Database Connection ({connection_status})", expanded=not current_connection):
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("1. Connect Database")
        db_conn_input = st.text_input(
            "SQL Connection String", 
            value=current_connection if current_connection else "",
            type="password",
            help="postgresql://user:pass@host/db\nNote: If your password has special characters (e.g. @), you MUST URL-encode them! (e.g. @ -> %40)"
        )
        if st.button("Save Connection"):
            try:
                # Test connection before saving
                from sqlalchemy import create_engine, text
                engine = create_engine(db_conn_input)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                
                auth_mongo.update_thread_db(st.session_state.current_thread_id, db_conn_input)
                st.success("Connection successful! Saved and ready to chat. 🟢")
                # Wait a moment for user to see success message before rerun
                import time
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Connection Failed: {e}")


    with col2:
        st.subheader("2. Upload Data (Excel/CSV)")
        
        with st.form("upload_form", clear_on_submit=False):
            uploaded_file = st.file_uploader("Upload file to Database", type=['csv', 'xlsx', 'xls'], key="file_obj")
            submitted = st.form_submit_button("Upload to SQL")
            
            if submitted:
                # Fallback: If no current connection, try to use the input field from Col 1
                if not current_connection and db_conn_input:
                    try:
                        from sqlalchemy import create_engine, text
                        # Test it first
                        engine = create_engine(db_conn_input)
                        with engine.connect() as conn:
                            conn.execute(text("SELECT 1"))
                        
                        # It works! Save it and use it.
                        current_connection = db_conn_input
                        auth_mongo.update_thread_db(st.session_state.current_thread_id, current_connection)
                        st.toast("Auto-saved connection & starting upload... 🚀")
                    except Exception as e:
                        st.error(f"❌ Could not auto-connect: {e}")

                if not current_connection:
                    st.warning("Please connect a database first (or enter the string in the box left)!")
                elif not uploaded_file:
                    st.warning("Please select a file to upload.")
                else:
                    with st.spinner("Uploading..."):
                        success, result = etl_logic.upload_file_to_sql(uploaded_file, current_connection)
                        if success:
                            auth_mongo.update_thread_db(st.session_state.current_thread_id, current_connection, table_name=result)
                            st.success(f"Uploaded and created table: `{result}`")
                            # Add system message to chat
                            auth_mongo.add_message(
                                st.session_state.current_thread_id, 
                                "system", 
                                f"Uploaded file `{uploaded_file.name}` into table `{result}`."
                            )
                            # time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"Error: {result}")

    # Schema Debugger
    with st.expander("View Database Schema"):
        if current_connection:
            try:
                # Use a temporary agent or the main one if initialized
                # Just for display
                from sql_agent import SQLAgent
                temp_agent = SQLAgent(current_connection)
                schema_info = temp_agent.get_schema_info()
                st.text(schema_info)
            except Exception as e:
                st.error(f"Error fetching schema: {e}")
        else:
            st.info("Connect to a database to view schema.")
            
# --- Chat Interface ---
if not current_connection:
    st.warning("Please connect a database to start chatting.")
    st.stop()

agent = SQLAgent(current_connection)

# Display Message History
messages = auth_mongo.get_messages(st.session_state.current_thread_id)
for msg in messages:
    role = msg['role']
    content = msg['content']
    with st.chat_message(role):
        st.markdown(content)

# --- Pending Approval UI ---
if "pending_unsafe_query" not in st.session_state:
    st.session_state.pending_unsafe_query = None

if st.session_state.pending_unsafe_query:
    st.warning("⚠️ **Potentially Destructive Query Detected**")
    query_to_run = st.session_state.pending_unsafe_query['query']
    reason = st.session_state.pending_unsafe_query['reason']
    
    st.code(query_to_run, language="sql")
    st.info(f"Reason: {reason}")
    st.write("Do you want to execute this?")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Yes, Execute", type="primary", use_container_width=True):
            with st.spinner("Executing..."):
                auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Approved & Executed: `{query_to_run}`")
                success, result = agent.execute_query(query_to_run)
                if success:
                    if isinstance(result, pd.DataFrame):
                        # st.dataframe(result) # Don't show here, let it be in history or just success
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Result:\n{result.to_markdown(index=False)}")
                    else:
                        st.success(result)
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", result)
                else:
                    st.error(f"Error: {result}")
                    auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Error: {result}")
            
            st.session_state.pending_unsafe_query = None
            st.rerun()
            
    with col2:
        if st.button("❌ No, Cancel", use_container_width=True):
            auth_mongo.add_message(st.session_state.current_thread_id, "assistant", "Action blocked by user.")
            st.session_state.pending_unsafe_query = None
            st.rerun()

# Chat Input
if prompt := st.chat_input("Ask a question about your data..."):
    # If there's a pending query, don't allow new input until resolved (optional, but cleaner)
    if st.session_state.pending_unsafe_query:
        st.warning("Please approve or reject the pending query above first.")
        st.stop()

    # Add User Message
    auth_mongo.add_message(st.session_state.current_thread_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)
        
    # Generate Response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        # First gather schema
        schema_context = agent.get_schema_info(active_table)
        
        # Generate SQL
        sql_query = agent.generate_query(prompt, schema_context, active_table=active_table)
        
        message_placeholder.markdown(f"**Generated SQL:**\n```sql\n{sql_query}\n```")
        
        # Check Safety
        is_safe, reason_or_preview = agent.check_safety(sql_query)
        
        if not is_safe:
            # Dangerous!
            st.session_state.pending_unsafe_query = {
                "query": sql_query,
                "reason": reason_or_preview
            }
            auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Generated SQL (WAITING APPROVAL): `{sql_query}`")
            st.rerun()
            
        else:
            # Safe to run
            with st.spinner("Running query..."):
                success, result = agent.execute_query(sql_query)
                if success:
                    if isinstance(result, pd.DataFrame):
                        st.dataframe(result)
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Executed SQL: `{sql_query}`\n\nResult:\n{result.to_markdown(index=False)}")
                    else:
                        st.success(result)
                        auth_mongo.add_message(st.session_state.current_thread_id, "assistant", result)
                else:
                    st.error(f"Error executing query: {result}")
                    auth_mongo.add_message(st.session_state.current_thread_id, "assistant", f"Error: {result}")

