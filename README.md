# 🤖 SQLMate
> **Your AI-Powered Data Assistant — Chat with SQL & MongoDB**

**SQLMate** is a secure, multi-user SaaS application that lets you **chat with your databases in plain English**. Connect to an existing SQL or MongoDB database, upload an Excel/CSV file, or spin up a Demo Database — and start querying instantly without writing a single line of code.

![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=Streamlit&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=MongoDB&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-AI-orange?style=for-the-badge)

---

## ✨ Features

### 🔌 Dual Database Support (Full Parity)
Both SQL and MongoDB modes support **identical features**, abstracting away their underlying query differences:

| Feature | SQL | MongoDB |
|---|:---:|:---:|
| Natural language queries | ✅ | ✅ |
| Conversation memory (last 10 turns) | ✅ | ✅ |
| Ambiguity clarifier | ✅ | ✅ |
| Multi-turn refinement | ✅ | ✅ |
| Auto-retry on error | ✅ | ✅ |
| Query/operation explanation | ✅ | ✅ |
| Destructive op approval | ✅ | ✅ |
| Chart visualization | ✅ | ✅ |
| Result pagination (100/page) | ✅ | ✅ |
| Thread auto-naming | ✅ | ✅ |
| File upload (CSV/Excel) | ✅ | ✅ |
| One-click Demo Database | ✅ | ❌ |

### 🧠 AI Engine
- **Llama 3.3 70B** via Groq — generates SQL or PyMongo operations (including complex Aggregation Pipelines for NoSQL).
- **FK-aware schema** — foreign keys and primary keys injected into context for accurate SQL JOINs.
- **Conversation memory** — last 10 chat turns sent with every LLM call for seamless follow-up questions.
- **Ambiguity clarifier** — asks a follow-up question before generating a query if the intent is unclear.
- **Multi-turn refinement** — *"now only top 5"* updates the previous query instead of forcing you to repeat yourself.
- **Auto-retry** — if a query fails, the error is sent back to the LLM to self-correct automatically.
- **Query explanation** — plain English explanation of every generated query/operation.

### 📤 ETL Pipeline
Upload **Excel or CSV** → automatic preprocessing:
- 🗑️ Drop junk/summary rows ("Total", "Grand Total")
- 📅 Standardize date columns → `YYYY-MM-DD`
- 🔢 Coerce mixed-type columns to numeric
- 🩹 Fill missing values (median for numbers, empty string for text)

### 🛡️ Safety First
- Destructive operations (`DELETE`, `UPDATE`, `DROP`, MongoDB `delete`/`update`) always require **human approval**.
- Preview of affected rows or filters shown before execution.
- All database credentials encrypted with **Fernet** (symmetric AES encryption) before storage.

### 📊 Visualization
- Auto-detects chart requests (*"show a bar chart of..."*).
- Renders **bar, line, pie, scatter, histogram** charts via Plotly.
- **Smart Dataframe Sanitization**: Automatically cleans unhashable NoSQL arrays and dictionaries so Plotly never crashes on complex MongoDB outputs.
- **Auto-Fallback**: If the LLM rate-limits or fails to define axes, the engine auto-infers from the DataFrame structure.

### 📐 Schema & Testing Tools
- **Demo Database** — Instantly spin up a local SQLite database populated with sample tables (Employees, Departments) for users without credentials.
- **Multi-table selector** — choose which SQL tables the AI has access to.
- **SQLite support** — drag and drop a `.db` file, no server needed.

### 💬 Chat Management
- Multi-user auth (Bcrypt password hashing).
- Persistent chat threads per user (stored securely in MongoDB Atlas).
- **Auto-named threads** — title generated quickly from your first question.
- Create, switch, and delete chat threads from the sidebar.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | [Streamlit](https://streamlit.io/) |
| AI Engine | [LangChain](https://www.langchain.com/) + [Groq](https://groq.com/) (Llama 3.3 70B) |
| SQL Connector | [SQLAlchemy](https://www.sqlalchemy.org/) |
| MongoDB Driver | [PyMongo](https://pymongo.readthedocs.io/) |
| ETL / Data | [Pandas](https://pandas.pydata.org/) |
| Charts | [Plotly](https://plotly.com/) |
| Auth & App DB | MongoDB Atlas |
| Encryption | `cryptography` (Fernet) |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- A **MongoDB Atlas** cluster (Free Tier works perfectly)
- A **Groq API Key** — get one free at [console.groq.com](https://console.groq.com/)

### Installation

```bash
git clone https://github.com/your-username/sqlmate.git
cd sqlmate
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

Create a `.env` file:
```
GROQ_API_KEY=gsk_...
MONGO_URI=mongodb+srv://<user>:<password>@cluster.mongodb.net/dbname
ENCRYPTION_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

Run the app:
```bash
streamlit run app.py
```

> **Supabase users:** Use the **Session Pooler** connection string (port `6543`) from your Supabase Dashboard → Connect, not the direct connection.

---

## 🔁 Three Ways to Connect

**Flow A — Existing Database**
1. Open a new chat → paste your SQL/MongoDB connection string → start chatting.

**Flow B — Upload a File**
1. Open a new chat → Upload Excel/CSV → choose SQL or MongoDB destination → SQLMate cleans, uploads, and connects automatically.

**Flow C — Try the Demo**
1. Open a new chat → click "**✨ Try Demo Database**" to instantly connect to an auto-generated sample SQL database.

---

## ☁️ Deployment
Ready to be deployed for free on **Streamlit Community Cloud** or Render.

---

## 🛡️ License
MIT License. Feel free to fork and modify!
