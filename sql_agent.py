import os
import re
import tempfile
import pandas as pd
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from sqlalchemy import create_engine, inspect, text

# Initialize Groq LLM (reads GROQ_API_KEY from env)
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)


class SQLAgent:
    def __init__(self, db_connection_string):
        self.db_uri = db_connection_string
        self.engine = create_engine(self.db_uri, isolation_level="AUTOCOMMIT")
        self.dialect = self._detect_dialect()

    def _detect_dialect(self):
        uri = self.db_uri.lower()
        if "mysql" in uri:
            return "mysql"
        elif "postgres" in uri:
            return "postgresql"
        elif "sqlite" in uri:
            return "sqlite"
        return "sql"

    # ── Feature 1: Table Discovery ────────────────────────────────────────────
    def get_table_list(self):
        """Returns a list of dicts: [{Table: name, Columns: col1, col2, ...}]"""
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

    # ── Feature 4: Schema with FK Injection ──────────────────────────────────
    def get_schema_info(self, table_name=None, focused_tables=None):
        """
        Returns schema as a readable string for the LLM prompt.
        Includes foreign key relationships for better JOIN accuracy (Feature 4).
        focused_tables: list of table names to include (Feature 14).
        """
        inspector = inspect(self.engine)
        try:
            all_tables = inspector.get_table_names()
            if not all_tables:
                return "No tables found in database. Please upload an Excel file or check your connection."

            # Feature 14: filter to focused tables if set
            tables = [t for t in all_tables if t in focused_tables] if focused_tables else all_tables

            all_schemas = []
            for table in tables:
                columns = inspector.get_columns(table)
                col_str = ", ".join(f"{c['name']} ({c['type']})" for c in columns)

                # Feature 4: FK relationships
                try:
                    fks = inspector.get_foreign_keys(table)
                    fk_lines = []
                    for fk in fks:
                        referred = fk.get("referred_table", "")
                        local_cols = ", ".join(fk.get("constrained_columns", []))
                        remote_cols = ", ".join(fk.get("referred_columns", []))
                        fk_lines.append(f"  FK: {table}.{local_cols} → {referred}.{remote_cols}")
                    fk_str = ("\n" + "\n".join(fk_lines)) if fk_lines else ""
                except Exception:
                    fk_str = ""

                # Feature 4: primary keys
                try:
                    pk = inspector.get_pk_constraint(table)
                    pk_cols = pk.get("constrained_columns", [])
                    pk_str = f"\n  PK: {', '.join(pk_cols)}" if pk_cols else ""
                except Exception:
                    pk_str = ""

                all_schemas.append(f"Table: {table}\nColumns: {col_str}{pk_str}{fk_str}")

            return "\n\n".join(all_schemas)
        except Exception as e:
            return f"Error fetching schema: {e}"


    # ── Safety Check ──────────────────────────────────────────────────────────
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

    # ── Feature 6: Ambiguity Clarifier ───────────────────────────────────────
    def needs_clarification(self, question, schema_context, chat_history=None):
        """
        Checks if the question is too vague to generate a reliable query.
        Accepts chat_history so it understands follow-up replies like "yes".
        Returns (needs_clarification: bool, clarifying_question: str)
        """
        system_prompt = (
            "You are a SQL assistant reviewing a user's question.\n\n"
            "Given the question and database schema below, decide:\n"
            "1. Is the question clear enough to generate a SQL query directly?\n"
            "2. If NOT clear, provide a short clarifying question to ask the user.\n\n"
            "RULES:\n"
            "- If the question is clear, respond exactly: CLEAR\n"
            "- If unclear, respond: UNCLEAR: <your clarifying question>\n"
            "- Keep the clarifying question concise (one sentence max).\n"
            "- Do NOT generate SQL.\n"
            "- If the conversation history already clarifies the intent, respond: CLEAR\n\n"
            f"Schema:\n{schema_context}"
        )
        msgs = [SystemMessage(content=system_prompt)]
        # Inject last few turns so LLM knows the conversation context
        for turn in (chat_history or []):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "assistant":
                from langchain_core.messages import AIMessage
                msgs.append(AIMessage(content=content))
        msgs.append(HumanMessage(content=question))
        try:
            response = llm.invoke(msgs)
            content = response.content.strip()
            if content.upper().startswith("UNCLEAR:"):
                clarifying_q = content[len("UNCLEAR:"):].strip()
                return True, clarifying_q
            return False, ""
        except Exception:
            return False, ""

    # ── Feature 3: Query Generation + Auto-Retry ─────────────────────────────
    def generate_query(self, user_question, schema_context, active_table=None,
                       focused_tables=None, chat_history=None):
        """Generates a SQL query from natural language using the Groq LLM."""
        return self._call_llm_for_query(user_question, schema_context, active_table,
                                        chat_history=chat_history)

    def generate_query_with_retry(self, user_question, schema_context, failed_query,
                                  error_message, active_table=None, chat_history=None):
        """
        Feature 3: Auto-retry — feeds the error back to the LLM to self-correct.
        Returns a corrected SQL query string.
        """
        retry_question = (
            f"The following SQL query failed with this error:\n\n"
            f"Query:\n```sql\n{failed_query}\n```\n\n"
            f"Error: {error_message}\n\n"
            f"Please fix the query to answer the original question:\n{user_question}"
        )
        return self._call_llm_for_query(retry_question, schema_context, active_table,
                                        chat_history=chat_history)

    # ── Feature 7: Multi-turn Refinement ─────────────────────────────────────
    def refine_query(self, previous_query, refinement_request, schema_context, chat_history=None):
        """
        Feature 7: Refines the last generated SQL query based on a follow-up instruction.
        """
        refine_prompt = (
            f"You have an existing SQL query:\n```sql\n{previous_query}\n```\n\n"
            f"The user wants to refine it: {refinement_request}\n\n"
            f"Return the updated/refined SQL query only. Do NOT rewrite from scratch unless necessary."
        )
        return self._call_llm_for_query(refine_prompt, schema_context,
                                        chat_history=chat_history)

    def _call_llm_for_query(self, user_question, schema_context, active_table=None,
                             chat_history=None):
        """Internal: calls the LLM with optional conversation history for memory."""
        focus = (
            f"\n11. **FOCUS**: Prioritize table `{active_table}` in your queries."
            if active_table else ""
        )
        system_content = f"""You are an expert SQL assistant.
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
9. Use JOIN conditions based on the FK relationships shown in Schema Context.
10. Use the Conversation History below to understand follow-up messages and context.
11. NEVER write Python, matplotlib, or Plotly code. The frontend handles charting. Just return the SQL data query.

Output: Return ONLY the SQL inside a ```sql ... ``` code block. No extra text.

Schema Context:
{schema_context}
"""
        # Build message list: system + history turns + current question
        msgs = [SystemMessage(content=system_content)]
        for turn in (chat_history or []):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "assistant":
                from langchain_core.messages import AIMessage
                msgs.append(AIMessage(content=content))
        msgs.append(HumanMessage(content=user_question))

        response = llm.invoke(msgs)
        content = response.content.strip()

        match = re.search(r"```sql\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.replace("```sql", "").replace("```", "").strip()

    # ── Feature 5: Query Explanation ─────────────────────────────────────────
    def explain_query(self, sql_query):
        """
        Feature 5: Returns a plain English explanation of what the SQL query does.
        """
        system_prompt = (
            "You are a SQL tutor. Explain the following SQL query in plain English.\n"
            "Be concise (2-4 sentences). Focus on WHAT it does, not HOW SQL works.\n"
            "Do not repeat the SQL. No code blocks."
        )
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=sql_query)]
        try:
            response = llm.invoke(messages)
            return response.content.strip()
        except Exception:
            return "Could not generate explanation."

    # ── Feature 15: Thread Auto-naming ───────────────────────────────────────
    def generate_thread_title(self, first_question):
        """
        Feature 15: Generates a short thread title from the first user question.
        """
        system_prompt = (
            "Generate a short chat title (4-6 words max) summarizing this database question.\n"
            "Return ONLY the title text. No quotes, no punctuation at the end."
        )
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=first_question)]
        try:
            response = llm.invoke(messages)
            title = response.content.strip().strip('"').strip("'")
            return title[:50]  # Safety cap
        except Exception:
            return "Chat"

    # ── Query Execution ───────────────────────────────────────────────────────
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


# ── Feature 12: SQLite Upload Helper ─────────────────────────────────────────
def sqlite_file_to_uri(uploaded_db_file):
    """
    Feature 12: Saves a Streamlit uploaded .db/.sqlite file to a temp location
    and returns a SQLite connection URI.
    """
    suffix = ".db"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_db_file.read())
    tmp.flush()
    tmp.close()
    return f"sqlite:///{tmp.name}"
