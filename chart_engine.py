"""
chart_engine.py — Robust chart visualization for SQLMate.

Fixes vs previous version:
- Fuzzy column matching: case-insensitive + strip whitespace
- Auto-fallback: if LLM picks a bad column, we infer from DataFrame types
- Explicit error returned to caller so failures are visible, not silent
"""

import re
import json
import pandas as pd
import plotly.express as px
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)

# ── Chart Intent Keywords ─────────────────────────────────────────────────────
CHART_KEYWORDS = [
    "chart", "graph", "plot", "visualize", "visualise", "draw",
    "histogram", "pie", "bar", "line", "scatter", "trend",
    "distribution", "compare", "breakdown", "correlation", "visual",
]


def is_chart_request(question: str) -> bool:
    """Returns True if the user's question is asking for a chart/graph."""
    q_lower = question.lower()
    return any(kw in q_lower for kw in CHART_KEYWORDS)


def _fuzzy_col(name: str, columns: list) -> str | None:
    """
    Case-insensitive, whitespace-insensitive column lookup.
    Returns the actual DataFrame column name or None.
    """
    if not name:
        return None
    name_clean = name.strip().lower()
    for col in columns:
        if col.strip().lower() == name_clean:
            return col
    return None


def _auto_infer_xy(df: pd.DataFrame):
    """
    Fallback: infer x (first categorical/string col) and y (first numeric col).
    Returns (x_col, y_col) — either can be None.
    """
    numeric_cols = list(df.select_dtypes(include="number").columns)
    text_cols    = list(df.select_dtypes(exclude="number").columns)
    x_col = text_cols[0]    if text_cols    else (numeric_cols[0] if numeric_cols else None)
    y_col = numeric_cols[0] if numeric_cols else None
    # Prevent x == y
    if x_col and y_col and x_col == y_col:
        y_col = numeric_cols[1] if len(numeric_cols) > 1 else None
    return x_col, y_col


def _ask_llm_for_chart_config(question: str, columns: list) -> dict | None:
    """
    Asks the LLM to pick chart type + axes.
    Returns a dict or None on failure.
    """
    col_list = ", ".join(columns)
    system_prompt = (
        "You are a data visualization expert.\n"
        "Given a user question and available columns, return a JSON object deciding the best chart.\n\n"
        "Rules:\n"
        "1. chart_type must be one of: bar, pie, line, histogram, scatter\n"
        "2. x must be an EXACT column name from the Available Columns list\n"
        "3. y must be an EXACT numeric column name (optional for histogram)\n"
        "4. title should be a short descriptive chart title\n"
        "5. Return ONLY a valid JSON object inside ```json ... ``` — nothing else.\n\n"
        f"Available columns: {col_list}\n\n"
        "Output example:\n"
        "```json\n"
        '{"chart_type": "bar", "x": "city", "y": "sales", "title": "Sales by City"}\n'
        "```"
    )
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=question)]
    try:
        response = llm.invoke(messages)
        content = response.content.strip()
        match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        raw = match.group(1) if match else content
        return json.loads(raw)
    except Exception:
        return None


def _build_chart(config: dict, df: pd.DataFrame):
    """
    Builds a Plotly figure from the LLM config dict.
    Uses fuzzy column matching + auto-inference fallback.
    Returns (plotly.Figure | None, error_str | None).
    """
    # Sanitize dataframe: convert unhashable types (lists/dicts) to strings so Plotly and unique() don't crash
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
            df[col] = df[col].astype(str)

    chart_type = config.get("chart_type", "bar").lower()
    x_col  = _fuzzy_col(config.get("x", ""), list(df.columns))
    y_col  = _fuzzy_col(config.get("y", ""), list(df.columns))
    title  = config.get("title", "Chart")

    # Fallback: auto-infer from DataFrame if LLM columns are wrong
    if not x_col or (chart_type in ("bar", "line", "scatter") and not y_col):
        auto_x, auto_y = _auto_infer_xy(df)
        if not x_col:
            x_col = auto_x
        if not y_col:
            y_col = auto_y

    try:
        if chart_type == "bar":
            if not x_col:
                return None, "Cannot determine x-axis column for bar chart."
            fig = px.bar(df, x=x_col, y=y_col, title=title,
                         color=x_col if len(df[x_col].unique()) <= 20 else None)

        elif chart_type == "pie":
            if not x_col:
                return None, "Cannot determine labels column for pie chart."
            values_col = y_col or (
                df.select_dtypes(include="number").columns[0]
                if len(df.select_dtypes(include="number").columns) > 0 else None
            )
            fig = px.pie(df, names=x_col, values=values_col, title=title)

        elif chart_type == "line":
            if not x_col or not y_col:
                return None, "Line chart needs both x and y columns."
            fig = px.line(df, x=x_col, y=y_col, title=title, markers=True)

        elif chart_type == "histogram":
            col = x_col or y_col
            if not col:
                return None, "No numeric column found for histogram."
            fig = px.histogram(df, x=col, title=title, nbins=20)

        elif chart_type == "scatter":
            if not x_col or not y_col:
                return None, "Scatter chart needs both x and y columns."
            fig = px.scatter(df, x=x_col, y=y_col, title=title,
                             trendline="ols" if len(df) >= 3 else None)
        else:
            # Unknown type → default to bar
            auto_x, auto_y = _auto_infer_xy(df)
            fig = px.bar(df, x=auto_x, y=auto_y, title=title)

        fig.update_layout(
            template="plotly_dark",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            title_font_size=16,
        )
        return fig, None

    except Exception as e:
        return None, str(e)


def detect_and_render_chart(user_question: str, df: pd.DataFrame, st_container) -> bool:
    """
    Main entry point. Returns True if a chart was rendered, False to fall back to table.
    """
    if not is_chart_request(user_question):
        return False

    if df is None or df.empty:
        return False

    config = _ask_llm_for_chart_config(user_question, list(df.columns))

    # If LLM config fails, build a best-guess config from DataFrame shape
    if not config:
        auto_x, auto_y = _auto_infer_xy(df)
        if not auto_x:
            return False
        config = {
            "chart_type": "bar" if auto_y else "histogram",
            "x": auto_x,
            "y": auto_y,
            "title": "Chart",
        }

    fig, err = _build_chart(config, df)

    if fig is None:
        if err:
            st_container.warning(f"⚠️ Could not build chart: {err}. Showing table instead.")
        return False

    st_container.plotly_chart(fig, use_container_width=True)
    return True


def chart_summary(config: dict) -> str:
    """Returns a short human-readable description of the chart for chat history."""
    if not config:
        return "📊 Chart rendered."
    ctype = config.get("chart_type", "chart").capitalize()
    x = config.get("x", "")
    y = config.get("y", "")
    title = config.get("title", "")
    if title:
        return f"📊 {ctype} chart: {title}"
    if x and y:
        return f"📊 {ctype} chart of `{y}` by `{x}`"
    if x:
        return f"📊 {ctype} chart of `{x}`"
    return f"📊 {ctype} chart rendered."
