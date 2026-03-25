"""
mongo_agent.py — Full CRUD AI Agent for MongoDB (NoSQL).

Supports:
  READ   → collection.find()
  UPDATE → collection.update_one() / update_many()
  DELETE → collection.delete_one() / delete_many()
  INSERT → collection.insert_one()

The LLM always returns a JSON operation dict so it never confuses
SQL syntax with PyMongo syntax:
  {"operation": "find",         "filter": {...}}
  {"operation": "update_one",   "filter": {...}, "update": {"$set": {...}}}
  {"operation": "update_many",  "filter": {...}, "update": {"$set": {...}}}
  {"operation": "delete_one",   "filter": {...}}
  {"operation": "delete_many",  "filter": {...}}
  {"operation": "insert_one",   "document": {...}}
"""

import re
import json
import pandas as pd
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)

# Operations that require user approval before execution
DESTRUCTIVE_OPERATIONS = {"update_one", "update_many", "delete_one", "delete_many"}


class MongoAgent:
    """
    Feature 2: Full-CRUD NoSQL AI Agent.
    Mirrors all SQL Agent capabilities — but generates PyMongo operations,
    NOT SQL, so the LLM cannot hallucinate SQL syntax for a MongoDB collection.
    """

    def __init__(self, collection):
        """collection: a live pymongo Collection object."""
        self.collection = collection

    # ── Schema Inference ─────────────────────────────────────────────────────
    def get_schema_info(self):
        """
        Samples up to 3 documents to infer fields and types.
        Returns a human-readable string passed to the LLM as context.
        """
        samples = list(self.collection.find({}, {"_id": 0}).limit(3))
        if not samples:
            return "Collection is empty. No schema could be inferred."
        first = samples[0]
        fields = {k: type(v).__name__ for k, v in first.items()}
        field_str = "\n".join(f"  - {k}: {t}" for k, t in fields.items())
        return (
            f"MongoDB Collection: `{self.collection.name}`\n"
            f"Fields:\n{field_str}\n\n"
            f"Sample document:\n{json.dumps(samples[0], default=str, indent=2)}"
        )

    # ── Query Generation ─────────────────────────────────────────────────────
    def generate_query(self, user_question, schema_context):
        """
        Uses the Groq LLM to generate a PyMongo operation dict from natural language.

        Always returns a JSON string with an "operation" key so the app can:
          - show it to the user for review (destructive ops)
          - execute it safely via execute_query()

        Uses SystemMessage + HumanMessage directly to avoid LangChain treating
        literal {} in schema/examples as template variables.
        """
        system_prompt = (
            "You are a MongoDB (NoSQL) expert. This is NOT SQL — never generate SQL.\n\n"
            "RULES:\n"
            "1. Analyse the user's intent and return ONE JSON operation dict.\n"
            "2. Always include an 'operation' key. Allowed values:\n"
            "   - 'find'        → read documents\n"
            "   - 'update_one'  → update the first matching document\n"
            "   - 'update_many' → update all matching documents\n"
            "   - 'delete_one'  → delete the first matching document\n"
            "   - 'delete_many' → delete all matching documents\n"
            "   - 'insert_one'  → insert a new document\n"
            "3. Use ONLY field names from the Schema Context below.\n"
            "4. For filters use PyMongo syntax: {\"field\": {\"$gt\": value}} etc.\n"
            '5. For case-insensitive text: {"field": {"$regex": "value", "$options": "i"}}\n'
            "6. For updates always use $set: {\"update\": {\"$set\": {\"field\": value}}}\n"
            "7. To return ALL documents use: {\"operation\": \"find\", \"filter\": {}}\n"
            "8. For 'find', you may optionally include:\n"
            "   - 'limit': integer — maximum number of documents to return (e.g. top 5 → limit: 5)\n"
            "   - 'sort': object — field + direction, where 1=ascending, -1=descending\n"
            "     example: {\"sort\": {\"salary\": -1}, \"limit\": 5} for top-5 by salary\n"
            "9. Return ONLY the JSON inside a ```json ... ``` code block. Nothing else.\n\n"
            f"Schema Context:\n{schema_context}\n\n"
            "OUTPUT EXAMPLES:\n"
            "```json\n"
            "{\"operation\": \"find\", \"filter\": {\"city\": \"Delhi\"}}\n"
            "```\n"
            "```json\n"
            "{\"operation\": \"find\", \"filter\": {}, \"sort\": {\"salary\": -1}, \"limit\": 5}\n"
            "```\n"
            "```json\n"
            "{\"operation\": \"update_one\", \"filter\": {\"user_id\": 1}, "
            "\"update\": {\"$set\": {\"user_id\": \"RTY54\"}}}\n"
            "```\n"
            "```json\n"
            "{\"operation\": \"delete_one\", \"filter\": {\"name\": \"Alice\"}}\n"
            "```\n"
            "```json\n"
            "{\"operation\": \"insert_one\", \"document\": {\"name\": \"Bob\", \"age\": 25}}\n"
            "```"
        )
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_question)]
        response = llm.invoke(messages)
        content  = response.content.strip()

        # Extract from ```json ... ``` block
        match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.replace("```json", "").replace("```", "").strip()

    # ── Safety Check ─────────────────────────────────────────────────────────
    def check_safety(self, operation_str):
        """
        Returns (is_safe, preview_description).
        Flags destructive operations (update/delete) for user approval.
        Mirrors SQLAgent.check_safety() behaviour.
        """
        try:
            op = json.loads(operation_str)
        except Exception:
            return True, "Safe"   # If we can't parse, let execute_query handle the error

        operation = op.get("operation", "find").lower()
        if operation in DESTRUCTIVE_OPERATIONS:
            filter_doc = op.get("filter", {})
            update_doc = op.get("update", {})
            preview = (
                f"Operation: `{operation}`\n"
                f"Filter: `{json.dumps(filter_doc)}`"
            )
            if update_doc:
                preview += f"\nChanges: `{json.dumps(update_doc)}`"
            return False, preview
        return True, "Safe"

    # ── Query Execution ───────────────────────────────────────────────────────
    def execute_query(self, operation_str):
        """
        Parses the LLM-generated JSON operation and runs the correct PyMongo method.

        Returns:
          (True, pd.DataFrame)  for find results
          (True, str)           for write confirmations
          (False, str)          for errors
        """
        try:
            op = json.loads(operation_str)
        except Exception:
            # Fallback: try old-style filter dict (plain find)
            try:
                filter_dict = eval(operation_str, {"__builtins__": {}})
                if isinstance(filter_dict, dict):
                    op = {"operation": "find", "filter": filter_dict}
                else:
                    return False, "Could not parse the operation."
            except Exception:
                return False, f"Invalid operation format: {operation_str}"

        operation = op.get("operation", "find").lower()

        try:
            # ── FIND ─────────────────────────────────────────────────────────
            if operation == "find":
                filter_dict = op.get("filter", {})
                sort_doc    = op.get("sort", None)
                limit_val   = int(op.get("limit", 200))

                cursor = self.collection.find(filter_dict, {"_id": 0})
                if sort_doc:
                    # PyMongo sort() expects a list of (field, direction) tuples
                    sort_list = list(sort_doc.items())
                    cursor = cursor.sort(sort_list)
                cursor = cursor.limit(limit_val)

                docs = list(cursor)
                if not docs:
                    return True, pd.DataFrame()
                return True, pd.DataFrame(docs)

            # ── UPDATE ONE ───────────────────────────────────────────────────
            elif operation == "update_one":
                filter_dict = op.get("filter", {})
                update_dict = op.get("update", {})
                result = self.collection.update_one(filter_dict, update_dict)
                return True, f"✅ Updated {result.modified_count} document(s)."

            # ── UPDATE MANY ──────────────────────────────────────────────────
            elif operation == "update_many":
                filter_dict = op.get("filter", {})
                update_dict = op.get("update", {})
                result = self.collection.update_many(filter_dict, update_dict)
                return True, f"✅ Updated {result.modified_count} document(s)."

            # ── DELETE ONE ───────────────────────────────────────────────────
            elif operation == "delete_one":
                filter_dict = op.get("filter", {})
                result = self.collection.delete_one(filter_dict)
                return True, f"🗑️ Deleted {result.deleted_count} document(s)."

            # ── DELETE MANY ──────────────────────────────────────────────────
            elif operation == "delete_many":
                filter_dict = op.get("filter", {})
                result = self.collection.delete_many(filter_dict)
                return True, f"🗑️ Deleted {result.deleted_count} document(s)."

            # ── INSERT ONE ───────────────────────────────────────────────────
            elif operation == "insert_one":
                document = op.get("document", {})
                result = self.collection.insert_one(document)
                return True, f"✅ Inserted 1 document (id: `{result.inserted_id}`)."

            else:
                return False, f"Unknown operation: `{operation}`"

        except Exception as e:
            return False, str(e)
