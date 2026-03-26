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
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)

# Operations that require user approval before execution
DESTRUCTIVE_OPERATIONS = {"update_one", "update_many", "delete_one", "delete_many"}


class MongoAgent:
    """
    Full-CRUD NoSQL AI Agent with conversation memory (chat_history).
    Feature-parity with SQLAgent: clarification, refinement, auto-retry, explanation.
    """

    def __init__(self, collection):
        """collection: a live pymongo Collection object."""
        self.collection = collection

    # ── Schema Inference ──────────────────────────────────────────────────────
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

    # ── Ambiguity Clarifier (mirrors SQLAgent) ────────────────────────────────
    def needs_clarification(self, question, schema_context, chat_history=None):
        """
        Checks if the question is too vague to generate a reliable operation.
        Accepts chat_history so it understands follow-up replies like 'yes'.
        Returns (needs_clarification: bool, clarifying_question: str)
        """
        system_prompt = (
            "You are a MongoDB assistant reviewing a user's question.\n\n"
            "Given the question and collection schema below, decide:\n"
            "1. Is the question clear enough to generate a MongoDB operation directly?\n"
            "2. If NOT clear, provide a short clarifying question to ask the user.\n\n"
            "RULES:\n"
            "- If the question is clear, respond exactly: CLEAR\n"
            "- If unclear, respond: UNCLEAR: <your clarifying question>\n"
            "- Keep the clarifying question concise (one sentence max).\n"
            "- Do NOT generate any code.\n"
            "- If the conversation history already clarifies the intent, respond: CLEAR\n\n"
            f"Schema:\n{schema_context}"
        )
        msgs = [SystemMessage(content=system_prompt)]
        for turn in (chat_history or []):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "assistant":
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

    # ── Query Generation with chat_history ───────────────────────────────────
    def generate_query(self, user_question, schema_context, chat_history=None):
        """
        Uses the Groq LLM to generate a PyMongo operation dict from natural language.
        Accepts chat_history for multi-turn conversation memory.
        """
        system_prompt = (
            "You are a MongoDB (NoSQL) expert. This is NOT SQL — never generate SQL.\n\n"
            "RULES:\n"
            "1. Analyse the user's intent and return ONE JSON operation dict.\n"
            "2. Always include an 'operation' key. Allowed values:\n"
            "   - 'find'        → read documents\n"
            "   - 'aggregate'   → analytical queries (group by, count, sum, average, etc.)\n"
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
            "   - 'limit': integer — maximum number of documents to return\n"
            "   - 'sort': object — field + direction, 1=ascending, -1=descending\n"
            "9. For 'aggregate', provide the aggregation array in the 'pipeline' key.\n"
            "10. Return ONLY the JSON inside a ```json ... ``` code block. Nothing else.\n"
            "11. Use the Conversation History to understand follow-up context.\n"
            "12. NEVER write Python, matplotlib, or Plotly code. The frontend handles charting. Just return the JSON data query.\n"
            "13. In 'aggregate', if you use '$group', always add a '$project' stage right after it to alias '_id' back to the original grouping field name (e.g. rename '_id' to 'gender').\n\n"
            f"Schema Context:\n{schema_context}\n\n"
            "OUTPUT EXAMPLES:\n"
            "```json\n"
            "{\"operation\": \"find\", \"filter\": {\"city\": \"Delhi\"}}\n"
            "```\n"
            "```json\n"
            "{\"operation\": \"aggregate\", \"pipeline\": [{\"$group\": {\"_id\": \"$gender\", \"count\": {\"$sum\": 1}}}, {\"$project\": {\"gender\": \"$_id\", \"count\": 1, \"_id\": 0}}]}\n"
            "```\n"
            "```json\n"
            "{\"operation\": \"update_one\", \"filter\": {\"user_id\": 1}, "
            "\"update\": {\"$set\": {\"user_id\": \"RTY54\"}}}\n"
            "```"
        )
        msgs = [SystemMessage(content=system_prompt)]
        for turn in (chat_history or []):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "assistant":
                msgs.append(AIMessage(content=content))
        msgs.append(HumanMessage(content=user_question))

        response = llm.invoke(msgs)
        content  = response.content.strip()

        match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.replace("```json", "").replace("```", "").strip()

    # ── Refinement (mirrors SQLAgent.refine_query) ────────────────────────────
    def refine_query(self, previous_op, refinement_request, schema_context, chat_history=None):
        """
        Refines the last generated MongoDB operation based on a follow-up instruction.
        E.g.: 'only top 5', 'sort by salary', 'filter by city Delhi'
        """
        refine_prompt = (
            f"You have an existing MongoDB operation:\n```json\n{previous_op}\n```\n\n"
            f"The user wants to refine it: {refinement_request}\n\n"
            f"Return the updated/refined MongoDB JSON operation only."
        )
        return self.generate_query(refine_prompt, schema_context, chat_history=chat_history)

    # ── Auto-retry on error (mirrors SQLAgent) ────────────────────────────────
    def generate_query_with_retry(self, user_question, schema_context,
                                  failed_op, error_message, chat_history=None):
        """
        Auto-retry: feeds the error back to the LLM to self-correct.
        Returns a corrected operation string.
        """
        retry_prompt = (
            f"The following MongoDB operation failed with this error:\n\n"
            f"Operation:\n```json\n{failed_op}\n```\n\n"
            f"Error: {error_message}\n\n"
            f"Please fix the operation to answer the original question:\n{user_question}"
        )
        return self.generate_query(retry_prompt, schema_context, chat_history=chat_history)

    # ── Query Explanation (mirrors SQLAgent.explain_query) ────────────────────
    def explain_query(self, operation_str):
        """
        Returns a plain English explanation of what the MongoDB operation does.
        """
        system_prompt = (
            "You are a MongoDB expert tutor. Explain the following MongoDB operation "
            "in plain English.\n"
            "Be concise (2-4 sentences). Focus on WHAT it does, not HOW MongoDB works.\n"
            "Do not repeat the JSON. No code blocks."
        )
        msgs = [SystemMessage(content=system_prompt), HumanMessage(content=operation_str)]
        try:
            response = llm.invoke(msgs)
            return response.content.strip()
        except Exception:
            return "Could not generate explanation."

    # ── Thread Auto-naming (mirrors SQLAgent) ─────────────────────────────────
    def generate_thread_title(self, first_question):
        """
        Generates a short thread title from the first user question.
        """
        system_prompt = (
            "Generate a short chat title (4-6 words max) summarizing this database question.\n"
            "Return ONLY the title text. No quotes, no punctuation at the end."
        )
        msgs = [SystemMessage(content=system_prompt), HumanMessage(content=first_question)]
        try:
            response = llm.invoke(msgs)
            return response.content.strip().strip('"').strip("'")[:50]
        except Exception:
            return "Chat"

    # ── Safety Check ──────────────────────────────────────────────────────────
    def check_safety(self, operation_str):
        """
        Returns (is_safe, preview_description).
        Flags destructive operations (update/delete) for user approval.
        """
        try:
            op = json.loads(operation_str)
        except Exception:
            return True, "Safe"

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
                    sort_list = list(sort_doc.items())
                    cursor = cursor.sort(sort_list)
                cursor = cursor.limit(limit_val)

                docs = list(cursor)
                if not docs:
                    return True, pd.DataFrame()
                return True, pd.DataFrame(docs)

            # ── AGGREGATE ────────────────────────────────────────────────────
            elif operation == "aggregate":
                pipeline = op.get("pipeline", [])
                cursor = self.collection.aggregate(pipeline)
                docs = list(cursor)
                if not docs:
                    return True, pd.DataFrame()
                return True, pd.DataFrame(docs)

            # ── UPDATE ONE ───────────────────────────────────────────────────
            elif operation == "update_one":
                result = self.collection.update_one(op.get("filter", {}), op.get("update", {}))
                return True, f"✅ Updated {result.modified_count} document(s)."

            # ── UPDATE MANY ──────────────────────────────────────────────────
            elif operation == "update_many":
                result = self.collection.update_many(op.get("filter", {}), op.get("update", {}))
                return True, f"✅ Updated {result.modified_count} document(s)."

            # ── DELETE ONE ───────────────────────────────────────────────────
            elif operation == "delete_one":
                result = self.collection.delete_one(op.get("filter", {}))
                return True, f"🗑️ Deleted {result.deleted_count} document(s)."

            # ── DELETE MANY ──────────────────────────────────────────────────
            elif operation == "delete_many":
                result = self.collection.delete_many(op.get("filter", {}))
                return True, f"🗑️ Deleted {result.deleted_count} document(s)."

            # ── INSERT ONE ───────────────────────────────────────────────────
            elif operation == "insert_one":
                result = self.collection.insert_one(op.get("document", {}))
                return True, f"✅ Inserted 1 document (id: `{result.inserted_id}`)."

            else:
                return False, f"Unknown operation: `{operation}`"

        except Exception as e:
            return False, str(e)
