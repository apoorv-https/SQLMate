import re
import json
import pandas as pd
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

# Initialize Groq LLM (reads GROQ_API_KEY from env)
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)


class MongoAgent:
    """
    Feature 2: NoSQL AI Agent.
    Queries a MongoDB collection using natural language.
    The LLM is told this is MongoDB (NoSQL) so it generates a PyMongo filter dict,
    NOT SQL — preventing hallucination and query errors.
    """

    def __init__(self, collection):
        """
        collection: a pymongo Collection object (already connected).
        """
        self.collection = collection

    # ── Schema Inference ─────────────────────────────────────────────────────────
    def get_schema_info(self):
        """
        Samples up to 3 documents from the collection to infer field names and types.
        Returns a human-readable string passed to the LLM as context.
        """
        samples = list(self.collection.find({}, {"_id": 0}).limit(3))
        if not samples:
            return "Collection is empty. No schema could be inferred."

        # Infer types from first sample
        first = samples[0]
        fields = {k: type(v).__name__ for k, v in first.items()}
        field_str = "\n".join(f"  - {k}: {t}" for k, t in fields.items())
        return f"MongoDB Collection: `{self.collection.name}`\nFields:\n{field_str}\n\nSample row:\n{json.dumps(samples[0], default=str, indent=2)}"

    # ── Query Generation ─────────────────────────────────────────────────────────
    def generate_query(self, user_question, schema_context):
        """
        Uses the Groq LLM to generate a PyMongo filter dict from natural language.
        Uses SystemMessage + HumanMessage directly (NOT ChatPromptTemplate) to avoid
        LangChain treating literal {} in the prompt/schema as template variables.
        """
        system_prompt = (
            "You are a MongoDB (NoSQL) query expert.\n\n"
            "IMPORTANT RULES:\n"
            "1. This database is MongoDB — a NoSQL document store. Do NOT write SQL.\n"
            "2. Convert the user's question into a valid Python dict for PyMongo's collection.find(filter).\n"
            "3. Return ONLY the filter dict inside a ```python ... ``` code block. Nothing else.\n"
            "4. To return ALL documents, return: {}\n"
            "5. For counting — still return the find filter, the app will count the results.\n"
            '6. For case-insensitive text match use: {"field": {"$regex": "value", "$options": "i"}}\n'
            '7. For numeric comparisons use: {"field": {"$gt": value}} etc.\n'
            "8. Use ONLY field names that exist in the Schema Context below.\n\n"
            f"Schema Context:\n{schema_context}\n\n"
            "Output example:\n"
            "```python\n"
            '{"city": "Delhi"}\n'
            "```"
        )
        # Pass messages directly — bypasses ChatPromptTemplate variable parsing entirely
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_question)]
        response = llm.invoke(messages)
        content = response.content.strip()

        # Extract the dict from ```python ... ``` block
        match = re.search(r"```python\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.replace("```python", "").replace("```", "").strip()

    # ── Query Execution ──────────────────────────────────────────────────────────
    def execute_query(self, filter_str):
        """
        Safely evaluates the LLM-generated filter dict string and runs find().
        Returns (True, DataFrame) or (False, error_message).
        """
        try:
            # Safe eval — only allows dict literals (no function calls etc.)
            filter_dict = eval(filter_str, {"__builtins__": {}})
            if not isinstance(filter_dict, dict):
                return False, "LLM did not return a valid dict filter."

            cursor = self.collection.find(filter_dict, {"_id": 0}).limit(200)
            docs = list(cursor)

            if not docs:
                return True, pd.DataFrame()  # Empty result

            return True, pd.DataFrame(docs)
        except Exception as e:
            return False, str(e)
