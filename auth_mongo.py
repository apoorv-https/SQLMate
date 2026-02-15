import os
import bcrypt
import streamlit as st
from pymongo import MongoClient
from cryptography.fernet import Fernet
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Initialize MongoDB Client
# Uses st.secrets if available (Streamlit Cloud), otherwise environment variables
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    MONGO_URI = os.getenv("MONGODB_URL")

if not MONGO_URI:
    try:
        if "MONGO_URI" in st.secrets:
            MONGO_URI = st.secrets["MONGO_URI"]
        elif "MONGODB_URL" in st.secrets:
            MONGO_URI = st.secrets["MONGODB_URL"]
    except Exception:
        pass # Secrets file not found

if not MONGO_URI:
    st.error("🚨 `MONGO_URI` not found! Please check your `.env` file or Streamlit secrets.")
    st.stop()

# Validate URI format roughly to prevent "localhost" defaults if garbage is passed
if "localhost" in MONGO_URI or "127.0.0.1" in MONGO_URI:
    st.warning("⚠️ You are connecting to `localhost`. If this is deployed or you don't have a local Mongo, this will fail. Use MongoDB Atlas.")


try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) # 5s timeout instead of 30s
    # Only verify connection if we actually try to use it, 
    # but lazy connection is standard. 
    # We could do client.admin.command('ping') here to fail fast, 
    # but that slows down startup. Let's rely on the operation failure.
    db = client.get_database("sentient_sql_db")
    users_collection = db.users
    threads_collection = db.threads
    messages_collection = db.messages
except Exception as e:
    st.error(f"❌ Connection to MongoDB failed: {e}")
    st.stop()

# Encryption Key Management
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    try:
        if "ENCRYPTION_KEY" in st.secrets:
            ENCRYPTION_KEY = st.secrets["ENCRYPTION_KEY"]
    except Exception:
        pass

if not ENCRYPTION_KEY:
    # Generate a key if none exists (for dev/testing only - in prod this should be fixed)
    # WARNING: This means data encrypted in this session won't be decryptable in the next if the key changes!
    ENCRYPTION_KEY = Fernet.generate_key()

cipher_suite = Fernet(ENCRYPTION_KEY)

def encrypt_string(text):
    if not text: return None
    return cipher_suite.encrypt(text.encode()).decode()

def decrypt_string(text):
    if not text: return None
    return cipher_suite.decrypt(text.encode()).decode()

def sign_up(username, password):
    """Creates a new user."""
    if users_collection.find_one({"username": username}):
        return False, "Username already exists."
    
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    user_id = users_collection.insert_one({
        "username": username,
        "password": hashed_password
    }).inserted_id
    
    return True, str(user_id)

def login(username, password):
    """Authenticates a user."""
    user = users_collection.find_one({"username": username})
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
        return True, str(user['_id'])
    return False, None

def create_thread(user_id, title="New Chat"):
    """Creates a new chat thread."""
    # Find last thread to inherit connection
    last_thread = threads_collection.find_one({"user_id": user_id}, sort=[("created_at", -1)])
    db_conn_str = last_thread.get("db_connection_string") if last_thread else None
    
    thread_id = threads_collection.insert_one({
        "user_id": user_id,
        "title": title,
        "created_at": datetime.utcnow(),
        "db_connection_string": db_conn_str,
        "active_table_name": None
    }).inserted_id
    return str(thread_id)

def get_user_threads(user_id):
    """Retrieves all threads for a user."""
    return list(threads_collection.find({"user_id": user_id}).sort("created_at", -1))

def delete_thread(thread_id):
    """Deletes a thread and its messages."""
    from bson.objectid import ObjectId
    try:
        # Delete messages first
        messages_collection.delete_many({"thread_id": str(thread_id)})
        # Delete thread
        threads_collection.delete_one({"_id": ObjectId(thread_id)})
        return True
    except Exception as e:
        print(f"Error deleting thread: {e}")
        return False

def update_thread_db(thread_id, db_connection_string, table_name=None):
    """Updates the thread with the DB connection info."""
    from bson.objectid import ObjectId
    
    encrypted_conn = encrypt_string(db_connection_string)
    update_data = {"db_connection_string": encrypted_conn}
    if table_name:
        update_data["active_table_name"] = table_name
        
    result = threads_collection.update_one(
        {"_id": ObjectId(thread_id)},
        {"$set": update_data}
    )
    # Debug info
    if result.modified_count == 0:
        print(f"DEBUG: No document updated for thread_id {thread_id}")

def get_thread_details(thread_id):
    """Gets thread details including decrypted connection string."""
    from bson.objectid import ObjectId
    thread = threads_collection.find_one({"_id": ObjectId(thread_id)})
    if thread and thread.get("db_connection_string"):
        thread["decrypted_db_connection_string"] = decrypt_string(thread["db_connection_string"])
    return thread

def add_message(thread_id, role, content):
    """Adds a message to the thread history."""
    messages_collection.insert_one({
        "thread_id": thread_id,
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow()
    })

def get_messages(thread_id):
    """Retrieves messages for a thread."""
    return list(messages_collection.find({"thread_id": thread_id}).sort("timestamp", 1))
