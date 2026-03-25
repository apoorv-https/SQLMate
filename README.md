# 🤖 SQLMate
> **Your AI-Powered Data Assistant — Chat with SQL & MongoDB**

**SQLMate** is a secure, multi-user SaaS application that lets you **chat with your databases in plain English**. Connect to an existing SQL or MongoDB database, or upload an Excel/CSV file — and start querying instantly without writing a single line of code.

![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=Streamlit&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=MongoDB&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-AI-orange?style=for-the-badge)

---

## ✨ Key Features

### 🔌 Dual Database Support
- **SQL Mode** — Connect to any **PostgreSQL** or **MySQL** database via a raw connection string
- **MongoDB Mode** — Connect to your own **MongoDB Atlas** cluster (URI + collection name)
- Both modes support **direct connection** (no file upload needed) and **file upload**

### 📤 Smart File Upload (ETL Pipeline)
Upload **Excel or CSV** files and SQLMate automatically:
- 🗑️ Drops junk/summary rows (e.g. "Total", "Grand Total")
- 📅 Standardizes date columns → `YYYY-MM-DD`
- 🔢 Coerces mixed-type columns to numeric where possible
- 🩹 Fills missing values (median for numbers, empty string for text)
- Routes the cleaned data to your chosen **SQL table** or **MongoDB collection**

### 🧠 AI Query Engine
- **Natural Language → SQL / MongoDB** using **Llama 3.3 70B** via Groq
- Schema-aware: automatically fetches table names, column names, and types before querying
- Supports **focused table mode** — pin one table for more precise query generation
- Dialect-aware: generates `ILIKE` for PostgreSQL, `LOWER()` for MySQL

### 📊 Chart Visualization
- Automatically detects chart requests (e.g. *"show me a bar chart of sales by region"*)
- Renders **bar, line, pie, scatter** charts using Plotly
- Summarizes the chart type chosen in chat history

### 🛡️ Safety First — "The Safety Sandwich"
- Every generated query is scanned for **destructive operations**: `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `INSERT`
- Flagged queries **pause for human approval** — shows a preview of affected rows before execution
- Works identically for both SQL queries and MongoDB operations
- All database credentials are **encrypted with Fernet** (symmetric encryption) before storage

### 💬 Persistent Multi-User Chat
- User accounts with login / sign-up
- Each **chat thread** stores its own DB connection, active table, and full message history
- Thread management: create, switch, and delete chats from the sidebar

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
- A **MongoDB Atlas** cluster (Free Tier works)
- A **Groq API Key** — get one free at [console.groq.com](https://console.groq.com/)

### Installation

1. **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/sqlmate.git
    cd sqlmate
    ```

2. **Create a virtual environment**:
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Mac/Linux
    source venv/bin/activate
    ```

3. **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4. **Configure environment variables** — create a `.env` file:
    ```
    GROQ_API_KEY=gsk_...
    MONGO_URI=mongodb+srv://<user>:<password>@cluster.mongodb.net/dbname
    ENCRYPTION_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
    ```

5. **Run the app**:
    ```bash
    streamlit run app.py
    ```

---

## 🔁 Two Ways to Use SQLMate

### Flow A — Connect to an Existing Database
1. Open a new chat
2. Paste your **SQL connection string** or **MongoDB URI + collection name**
3. Start chatting — SQLMate reads your schema automatically

### Flow B — Upload a File
1. Open a new chat
2. Go to **Upload Excel / CSV**
3. Choose destination: **SQL Database** or **MongoDB**
4. Provide the target connection string
5. SQLMate cleans and uploads the file, then connects automatically

---

## ☁️ Deployment

Deploy for free on **Streamlit Community Cloud**:
👉 **[Read the Deployment Guide (DEPLOYMENT.md)](DEPLOYMENT.md)**

---

## 🛡️ License
MIT License. Feel free to fork and modify!
