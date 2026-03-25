"""
chart_engine.py — Chatbot-driven chart visualization using Plotly.

Usage in app.py:
    from chart_engine import detect_and_render_chart
    chart_shown = detect_and_render_chart(user_question, dataframe, st)
    if not chart_shown:
        st.dataframe(dataframe)   # fallback to table
"""

import re
import json
import pandas as pd
import plotly.express as px
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

# Reuse the same LLM already used by the agents
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)

# ── Chart Intent Keywords ─────────────────────────────────────────────────────
CHART_KEYWORDS = [
    "chart", "graph", "plot", "visualize", "visualise", "draw",
    "histogram", "pie", "bar", "line", "scatter", "trend",
    "distribution", "compare", "breakdown", "correlation",
]


def is_chart_request(question: str) -> bool:
    """Returns True if the user's question is asking for a chart/graph."""
    q_lower = question.lower()
    return any(kw in q_lower for kw in CHART_KEYWORDS)


def _ask_llm_for_chart_config(question: str, columns: list) -> dict | None:
    """
    Asks the Groq LLM to decide:
      - chart type (bar / pie / line / histogram / scatter)
      - x column
      - y column (optional for pie/histogram)
      - title

    Returns a dict or None on failure.
    """
    col_list = ", ".join(columns)
    system_prompt = (
        "You are a data visualization expert.\n"
        "Given a user question and available columns, return a JSON object deciding the best chart.\n\n"
        "Rules:\n"
        "1. chart_type must be one of: bar, pie, line, histogram, scatter\n"
        "2. x must be an exact column name from the list\n"
        "3. y must be an exact numeric column name (not needed for histogram, pie uses 'values')\n"
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
        if match:
            return json.loads(match.group(1))
        # Try parsing raw JSON if no code block
        return json.loads(content)
    except Exception:
        return None


def _build_chart(config: dict, df: pd.DataFrame):
    """
    Builds a Plotly figure from the LLM config dict.
    Returns a plotly Figure or None if the config is unusable.
    """
    chart_type = config.get("chart_type", "bar").lower()
    x_col      = config.get("x")
    y_col      = config.get("y")
    title      = config.get("title", "Chart")

    # Validate columns exist in df
    if x_col and x_col not in df.columns:
        x_col = None
    if y_col and y_col not in df.columns:
        y_col = None

    try:
        if chart_type == "bar":
            if not x_col:
                return None
            if y_col:
                fig = px.bar(df, x=x_col, y=y_col, title=title, color=x_col)
            else:
                fig = px.bar(df, x=x_col, title=title)

        elif chart_type == "pie":
            if not x_col:
                return None
            values_col = y_col if y_col else (
                df.select_dtypes(include="number").columns[0]
                if len(df.select_dtypes(include="number").columns) > 0 else None
            )
            if values_col:
                fig = px.pie(df, names=x_col, values=values_col, title=title)
            else:
                fig = px.pie(df, names=x_col, title=title)

        elif chart_type == "line":
            if not x_col:
                return None
            if y_col:
                fig = px.line(df, x=x_col, y=y_col, title=title, markers=True)
            else:
                return None

        elif chart_type == "histogram":
            col = x_col or y_col
            if not col:
                return None
            fig = px.histogram(df, x=col, title=title)

        elif chart_type == "scatter":
            if not x_col or not y_col:
                return None
            fig = px.scatter(df, x=x_col, y=y_col, title=title, trendline="ols"
                             if len(df) >= 3 else None)

        else:
            return None

        fig.update_layout(
            template="plotly_dark",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        return fig

    except Exception:
        return None


def detect_and_render_chart(user_question: str, df: pd.DataFrame, st_container) -> bool:
    """
    Main entry point. Called after a DataFrame result is obtained.

    1. Checks if the user asked for a chart.
    2. Asks LLM to pick chart type + axes.
    3. Builds and renders the Plotly chart.
    4. Returns True if a chart was rendered, False to fall back to table display.
    """
    if not is_chart_request(user_question):
        return False

    if df is None or df.empty:
        return False

    config = _ask_llm_for_chart_config(user_question, list(df.columns))
    if not config:
        return False

    fig = _build_chart(config, df)
    if fig is None:
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
