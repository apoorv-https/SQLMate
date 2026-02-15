# 🤖 SQLMate
> **Your AI-Powered SQL Data Assistant**

**SQLMate** (formerly Sentient SQL) is a secure, multi-user SaaS application that allows you to **chat with your SQL database** using natural language. Upload your Excel/CSV files, automatically convert them to SQL tables, and get instant answers without writing a single line of code.

![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=Streamlit&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=MongoDB&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-AI-orange?style=for-the-badge)

---

## ✨ Key Features

-   **💬 Natural Language to SQL**: Ask questions in plain English (e.g., *"Show me the top 5 sales by region"*).
-   **📂 Smart Data Ingestion**: Drag & drop **Excel** or **CSV** files. SQLMate automatically cleans column names, creates SQL tables, and uploads data instantly.
-   **🔌 Universal Connectivity**: Connect to **PostgreSQL**, **MySQL**, **SQLite**, and more.
-   **🧠 Intelligent Context**: The AI automatically fetches your database schema to understand table relationships.
-   **🔐 Enterprise-Grade Security**:
    -   **"Safety Sandwich"**: Intercepts destructive queries (`DROP`, `DELETE`, `UPDATE`) and asks for confirmation.
    -   **Encryption**: Database credentials are encrypted using `Fernet` (symmetric encryption) before being stored.
-   **💾 Persistent Chat History**: All conversations are saved automatically per user (stored in MongoDB).
-   **🚀 Auto-Connect**: Starts new chats with your last used database connection automatically.

---

## 🛠️ Tech Stack

-   **Frontend**: [Streamlit](https://streamlit.io/)
-   **Backend Logic**: Python
-   **AI Engine**: [LangChain](https://www.langchain.com/) + [Groq](https://groq.com/) (Llama 3 70B)
-   **Database (App Data)**: MongoDB Atlas (Users, Chats, History)
-   **Database (User Data)**: Any SQLAlchemy-compatible DB (Postgres, MySQL, SQLite)

---

## 🚀 Getting Started

### Prerequisites
-   Python 3.10+
-   A **MongoDB Atlas** Cluster (Free Tier works great).
-   A **Groq API Key** (Get it free at [console.groq.com](https://console.groq.com/)).

### Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/sqlmate.git
    cd sqlmate
    ```

2.  **Create a Virtual Environment**:
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Mac/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**:
    Create a `.env` file in the root directory:
    ```bash
    GROQ_API_KEY="gsk_..."
    MONGO_URI="mongodb+srv://<user>:<password>@cluster.mongodb.net/test"
    ENCRYPTION_KEY="ToGenerateRun_python_-c_from_cryptography.fernet_import_Fernet;print(Fernet.generate_key().decode())"
    # Optional (for MongoDB local testing)
    MONGODB_URL="mongodb://localhost:27017"
    ```

5.  **Run the App**:
    ```bash
    streamlit run app.py
    ```

---

## ☁️ Deployment

Deploy easily to **Streamlit Community Cloud** for free!
👉 **[Read the Deployment Guide (DEPLOYMENT.md)](DEPLOYMENT.md)**

---

## 🛡️ License
MIT License. Feel free to fork and modify!
