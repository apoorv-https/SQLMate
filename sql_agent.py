import os
import re
import pandas as pd  # Added missing import
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import create_engine, inspect, text

# Initialize Groq
# Expects GROQ_API_KEY in env
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0
)

class SQLAgent:
    def __init__(self, db_connection_string):
        self.db_uri = db_connection_string
        # Use AUTOCOMMIT to ensure changes are immediate and avoid hanging transactions
        self.engine = create_engine(self.db_uri, isolation_level="AUTOCOMMIT")
        self.dialect = self._detect_dialect()
        
    def _detect_dialect(self):
        if "mysql" in self.db_uri:
            return "mysql"
        elif "postgres" in self.db_uri:
            return "postgresql"
        else:
            return "sql" # Generic

    # ... (rest of methods)

    def execute_query(self, query):
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query))
                if result.returns_rows:
                    return True, pd.DataFrame(result.fetchall(), columns=result.keys())
                else:
                    # In AUTOCOMMIT mode, commit is implicit
                    return True, "Operation executed successfully."
        except Exception as e:
            return False, str(e)

    def get_schema_info(self, table_name=None):
        """
        Retrieves schema info for ALL tables to ensure AI has full context.
        """
        inspector = inspect(self.engine)
        all_schemas = []
        
        try:
            tables = inspector.get_table_names()
            if not tables:
                return "No tables found in database. Please upload an Excel file or check your connection."
                
            for table in tables:
                columns = inspector.get_columns(table)
                col_str = ", ".join([f"{col['name']} ({col['type']})" for col in columns])
                all_schemas.append(f"Table: {table}\nColumns: {col_str}")
                
            return "\n\n".join(all_schemas)
        except Exception as e:
            return f"Error fetching schema: {e}"

    def check_safety(self, query):
        """
        The Safety Sandwich.
        Returns (is_safe, reason/preview_query).
        """
        query_upper = query.upper()
        
        # 1. Intercept Destructive Commands
        destructive_keywords = ["UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "INSERT"]
        if any(keyword in query_upper for keyword in destructive_keywords):
            # 2. Generate Preview Query
            # This is a simplistic regex-based approach. 
            # In a real-world scenario, we'd need a robust SQL parser.
            # We try to extract the WHERE clause.
            where_match = re.search(r'WHERE\s+(.*)', query, re.IGNORECASE)
            where_clause = where_match.group(1) if where_match else ""
            
            # Simple heuristic to guess the table name if not provided (fragile)
            # A full SQL parser is better, but minimizing dependencies for now.
            # Assuming the AI generated valid SQL: "DELETE FROM table WHERE..."
            table_match = re.search(r'(FROM|UPDATE)\s+([a-zA-Z0-9_\`"\.]+)', query, re.IGNORECASE)
            table_name = table_match.group(2) if table_match else "unknown_table"
            
            preview_query = f"SELECT * FROM {table_name}"
            if where_clause:
                preview_query += f" WHERE {where_clause}"
            preview_query += " LIMIT 20"
            
            return False, preview_query
            
        return True, "Safe"

    def generate_query(self, user_question, schema_context, chat_history=[], active_table=None):
        """
        Generates SQL query from natural language.
        """
        
        table_focus_instruction = ""
        if active_table:
            table_focus_instruction = f"11. **FOCUS**: The user is currently working with table `{active_table}`. Prioritize this table in your queries."

        system_prompt = fr"""You are an expert SQL assistant.
        Dialect: {self.dialect}
        
        Instructions:
        1. Convert the user's question into a syntactic SQL query.
        2. Use the provided schema context.
        3. Do NOT execute the query. Just return the SQL code.
        4. If the user asks to modify data (UPDATE, DELETE), generate the query but warn them it's checking safety.
        5. For MySQL use backticks (`), for PostgreSQL use double quotes (") for identifiers.
        6. **IMPORTANT**: Do NOT generate CLI commands (like `\\c`, `\\d`, `\\list`). Generate ONLY standard SQL.
        7. **IMPORTANT**: Do NOT attempt to CREATE DATABASE. Assume the database exists and you are connected. 
        8. **IMPORTANT**: When creating tables, ALWAYS use `CREATE TABLE IF NOT EXISTS`.
        9. **TIP**: For WHERE clauses involving text, use `ILIKE` (PostgreSQL) or `LOWER(col) = LOWER(val)` to ensure case-insensitive matching unless case is explicitly important.
        10. **CRITICAL**: If the Schema Context below says "No tables found", do NOT generate SQL. Instead, reply EXACTLY: "I cannot see any tables in the database. Please upload an Excel file or check your connection."
        {table_focus_instruction}
        
        Output Format:
        Return ONLY the raw SQL query inside a markdown code block (```sql ... ```).
        Do NOT include any conversational text, explanations, or warnings outside the code block.
        
        Schema Context:
        {schema_context}
        """
        
        messages = [("system", system_prompt)] 
        # Add history can be simulated by appending text, 
        # or proper ChatMessage History if we want strictly structured.
        # For simplicity, we stick to user/ai single turn generation here, 
        # relying on the calling app to feed relevant context.
        
        messages.append(("human", user_question))
        
        prompt = ChatPromptTemplate.from_messages(messages)
        chain = prompt | llm
        
        response = chain.invoke({})
        content = response.content.strip()
        
        # Robust extraction of SQL code block
        code_block_match = re.search(r"```sql\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if code_block_match:
            return code_block_match.group(1).strip()
        
        # Fallback: simple code block
        code_block_match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
        if code_block_match:
            return code_block_match.group(1).strip()
            
        # Fallback: if no code blocks, assume the whole text is SQL but remove common conversational prefixes
        # This is risky, but better than nothing for simple models.
        # Ideally, we should demand JSON or strict format, but let's stick to text for now.
        return content.replace("```sql", "").replace("```", "").strip()

    def execute_query(self, query):
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query))
                if result.returns_rows:
                    return True, pd.DataFrame(result.fetchall(), columns=result.keys())
                else:
                    # In AUTOCOMMIT mode, commit is implicit
                    return True, f"Operation executed successfully. Rows affected: {result.rowcount}"
        except Exception as e:
            return False, str(e)
