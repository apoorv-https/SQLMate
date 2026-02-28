import os
import bcrypt
import streamlit as st
from pymongo import MongoClient
from cryptography.fernet import Fernet
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── MongoDB Connection ────────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGODB_URL")

if not MONGO_URI:
    try:
        MONGO_URI = st.secrets.get("MONGO_URI") or st.secrets.get("MONGODB_URL")
    except Exception:
        pass

if not MONGO_URI:
    st.error("🚨 `MONGO_URI` not found! Please check your `.env` file.")
    st.stop()

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client.get_database("sentient_sql_db")
    users_collection   = db.users
    threads_collection = db.threads
    messages_collection = db.messages
except Exception as e:
    st.error(f"❌ MongoDB connection failed: {e}")
    st.stop()

# ── Encryption ────────────────────────────────────────────────────────────────
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    try:
        ENCRYPTION_KEY = st.secrets.get("ENCRYPTION_KEY")
    except Exception:
        pass
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key()  # Dev only fallback

cipher_suite = Fernet(ENCRYPTION_KEY)


def get_db():
    """Exposes the MongoDB database object so other modules can get collections."""
    return db


def encrypt_string(text):
    if not text:
        return None
    return cipher_suite.encrypt(text.encode()).decode()


def decrypt_string(text):
    if not text:
        return None
    return cipher_suite.decrypt(text.encode()).decode()


# ── Auth ─────────────────────────────────────────────────────────────────────
def sign_up(username, password):
    """Creates a new user."""
    if users_collection.find_one({"username": username}):
        return False, "Username already exists."
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    user_id = users_collection.insert_one({"username": username, "password": hashed}).inserted_id
    return True, str(user_id)


def login(username, password):
    """Authenticates a user."""
    user = users_collection.find_one({"username": username})
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
        return True, str(user['_id'])
    return False, None


# ── Thread Management ─────────────────────────────────────────────────────────
def create_thread(user_id, title="New Chat"):
    """Creates a new chat thread. Each chat starts fresh — no inherited connection."""
    thread_id = threads_collection.insert_one({
        "user_id": user_id,
        "title": title,
        "created_at": datetime.utcnow(),
        "db_connection_string": None,       # Always starts blank — user must connect per chat
        "active_table_name": None,
        "mongo_collection_name": None,      # Feature 2: set when Excel is uploaded to MongoDB
    }).inserted_id
    return str(thread_id)


def get_user_threads(user_id):
    """Returns all threads for a user, newest first."""
    return list(threads_collection.find({"user_id": user_id}).sort("created_at", -1))


def delete_thread(thread_id):
    """Deletes a thread and all its messages."""
    from bson.objectid import ObjectId
    try:
        messages_collection.delete_many({"thread_id": str(thread_id)})
        threads_collection.delete_one({"_id": ObjectId(thread_id)})
        return True
    except Exception as e:
        print(f"Error deleting thread: {e}")
        return False


def update_thread_db(thread_id, db_connection_string=None, table_name=None, mongo_collection=None):
    """
    Updates the thread's connection info.
    - db_connection_string: SQL connection (encrypted at rest)
    - table_name: active SQL table
    - mongo_collection: Feature 2 — collection name for MongoDB mode
    """
    from bson.objectid import ObjectId
    update_data = {}
    if db_connection_string is not None:
        update_data["db_connection_string"] = encrypt_string(db_connection_string)
    if table_name is not None:
        update_data["active_table_name"] = table_name
    if mongo_collection is not None:
        update_data["mongo_collection_name"] = mongo_collection
    if update_data:
        threads_collection.update_one({"_id": ObjectId(thread_id)}, {"$set": update_data})


def get_thread_details(thread_id):
    """Returns thread document with decrypted SQL connection string."""
    from bson.objectid import ObjectId
    thread = threads_collection.find_one({"_id": ObjectId(thread_id)})
    if thread and thread.get("db_connection_string"):
        thread["decrypted_db_connection_string"] = decrypt_string(thread["db_connection_string"])
    return thread


# ── Messages ──────────────────────────────────────────────────────────────────
def add_message(thread_id, role, content):
    """Saves a chat message to the thread history."""
    messages_collection.insert_one({
        "thread_id": thread_id,
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow(),
    })


def get_messages(thread_id):
    """Returns all messages for a thread, ordered by time."""
    return list(messages_collection.find({"thread_id": thread_id}).sort("timestamp", 1))
