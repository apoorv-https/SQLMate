import os
import re
import pandas as pd
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import create_engine, inspect, text

# Initialize Groq LLM (reads GROQ_API_KEY from env)
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)


class SQLAgent:
    def __init__(self, db_connection_string):
        self.db_uri = db_connection_string
        # AUTOCOMMIT: changes are immediate, no hanging transactions
        self.engine = create_engine(self.db_uri, isolation_level="AUTOCOMMIT")
        self.dialect = self._detect_dialect()

    def _detect_dialect(self):
        if "mysql" in self.db_uri:
            return "mysql"
        elif "postgres" in self.db_uri:
            return "postgresql"
        return "sql"

    # ── Feature 1: Table Discovery ──────────────────────────────────────────────
    def get_table_list(self):
        """
        Returns a list of dicts: [{Table: name, Columns: col1, col2, ...}]
        Used to display all tables right after a connection is made.
        """
        try:
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
            result = []
            for t in tables:
                cols = inspector.get_columns(t)
                col_names = ", ".join(c["name"] for c in cols)
                result.append({"Table": t, "Columns": col_names})
            return result
        except Exception:
            return []

    # ── Schema for LLM Context ───────────────────────────────────────────────────
    def get_schema_info(self, table_name=None):
        """Returns full schema as a readable string for the LLM prompt."""
        inspector = inspect(self.engine)
        try:
            tables = inspector.get_table_names()
            if not tables:
                return "No tables found in database. Please upload an Excel file or check your connection."
            all_schemas = []
            for table in tables:
                columns = inspector.get_columns(table)
                col_str = ", ".join(f"{c['name']} ({c['type']})" for c in columns)
                all_schemas.append(f"Table: {table}\nColumns: {col_str}")
            return "\n\n".join(all_schemas)
        except Exception as e:
            return f"Error fetching schema: {e}"

    # ── Safety Check ─────────────────────────────────────────────────────────────
    def check_safety(self, query):
        """
        Returns (is_safe, preview_query).
        Flags destructive SQL for user approval before execution.
        """
        query_upper = query.upper()
        destructive = ["UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "INSERT"]
        if any(kw in query_upper for kw in destructive):
            where_match = re.search(r'WHERE\s+(.*)', query, re.IGNORECASE)
            where_clause = where_match.group(1) if where_match else ""
            table_match = re.search(r'(FROM|UPDATE)\s+([a-zA-Z0-9_`"\.]+)', query, re.IGNORECASE)
            table_name = table_match.group(2) if table_match else "unknown_table"
            preview = f"SELECT * FROM {table_name}"
            if where_clause:
                preview += f" WHERE {where_clause}"
            preview += " LIMIT 20"
            return False, preview
        return True, "Safe"

    # ── Query Generation ─────────────────────────────────────────────────────────
    def generate_query(self, user_question, schema_context, active_table=None):
        """Generates a SQL query from natural language using the Groq LLM."""
        focus = (
            f"\n11. **FOCUS**: Prioritize table `{active_table}` in your queries."
            if active_table else ""
        )
        system_prompt = f"""You are an expert SQL assistant.
Dialect: {self.dialect}

Instructions:
1. Convert the user's question into a valid SQL query.
2. Use the Schema Context below.
3. Do NOT execute the query — return SQL only.
4. Do NOT generate CLI commands (\\c, \\d, \\list). Pure SQL only.
5. Do NOT attempt to CREATE DATABASE. Assume you are already connected.
6. Use CREATE TABLE IF NOT EXISTS when creating tables.
7. For text comparisons use ILIKE (PostgreSQL) or LOWER()=LOWER() (MySQL).
8. If Schema Context says "No tables found", reply EXACTLY: "I cannot see any tables. Please upload a file or check your connection."{focus}

Output: Return ONLY the SQL inside a ```sql ... ``` code block. No extra text.

Schema Context:
{schema_context}
"""
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", user_question)])
        response = (prompt | llm).invoke({})
        content = response.content.strip()

        match = re.search(r"```sql\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.replace("```sql", "").replace("```", "").strip()

    # ── Query Execution ──────────────────────────────────────────────────────────
    def execute_query(self, query):
        """Runs a SQL query. Returns (True, DataFrame) or (True, message) or (False, error)."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query))
                if result.returns_rows:
                    return True, pd.DataFrame(result.fetchall(), columns=result.keys())
                return True, f"Done. Rows affected: {result.rowcount}"
        except Exception as e:
            return False, str(e)
