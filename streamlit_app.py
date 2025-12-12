import asyncio
import threading

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.utils.logger import get_logger
from src.tools.chem_scout_mcp_tools import SERVER
from src.database.db import init_db

from chem_scout_ai.common.backend import Gemini2p5Flash
from src.agents.router import classify_intent
from src.agents.factory import build_agents
from chem_scout_ai.common import types

logger = get_logger(__name__)


# ================================================================
# Start MCP server in the background (same idea as main.py)
# ================================================================
def _run_mcp():
    import uvicorn

    uvicorn.run(
        SERVER.streamable_http_app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


def start_mcp_background():
    """
    Start the MCP server only once per Streamlit session.
    """
    if "mcp_thread" in st.session_state:
        return

    thread = threading.Thread(target=_run_mcp, daemon=True)
    thread.start()
    st.session_state["mcp_thread"] = thread
    logger.info("MCP server started in background on http://127.0.0.1:8000/mcp")


# ================================================================
# One-time app initialization (DB, backend, agents)
# ================================================================
def init_app():
    if st.session_state.get("initialized"):
        return

    # 1) DB
    init_db()
    logger.info("Database initialized (Streamlit).")

    # 2) MCP server
    start_mcp_background()

    # 3) LLM backend (Gemini 2.5 Flash via Google)
    backend_cfg = Gemini2p5Flash()
    backend = backend_cfg.get_async_backend()
    logger.info(f"Backend initialized ({backend_cfg.name}).")

    # 4) Build agents (data + order)
    agents = build_agents(backend)
    # agents = { "data": (agent, chat), "order": (agent, chat) }

    st.session_state["backend"] = backend
    st.session_state["agents"] = agents
    st.session_state["initialized"] = True
    st.session_state.setdefault("chat_history", [])


# ================================================================
# Helper: send one message through router + proper agent
# ================================================================
async def handle_user_message(user_text: str):
    """
    1) Use router to choose data / order agent
    2) Call that agent
    3) Append messages to chat_history for UI
    """
    backend = st.session_state["backend"]
    agents = st.session_state["agents"]

    # 1) Decide which agent to use
    intent = await classify_intent(user_text, backend)
    logger.info(f"Router selected agent: {intent}")

    agent, chat = agents[intent]

    # 2) Add user message to this agent's chat
    user_msg = types.UserMessage(role="user", content=user_text)
    chat.append(user_msg)

    # Also store in UI chat history
    st.session_state["chat_history"].append(
        {"role": "user", "content": user_text}
    )

    # 3) Call the agent
    try:
        responses = await agent(chat=chat)
    except Exception as e:
        logger.exception("Agent error")
        st.session_state["chat_history"].append(
            {
                "role": "assistant",
                "content": f"⚠️ Agent error: `{e}`",
            }
        )
        return

    # 4) Process responses for display
    for msg in responses:
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", "")

        if not content:
            continue

        if role == "assistant":
            st.session_state["chat_history"].append(
                {"role": "assistant", "content": str(content)}
            )
        elif role == "tool":
            # Show tool output as JSON block
            st.session_state["chat_history"].append(
                {
                    "role": "assistant",
                    "content": f"🛠️ Tool output:\n```json\n{content}\n```",
                }
            )


# ================================================================
# Streamlit UI definition
# ================================================================
def main():
    st.set_page_config(page_title="ChemScout AI", page_icon="🧪")
    st.title("🧪 ChemScout AI – Web Prototype")
    st.caption("LLM-driven multi-agent system for chemical procurement")

    # Initialize once per session
    init_app()

    # Sidebar
    with st.sidebar:
        st.header("Session info")
        st.write("Agents: **data** & **order**")
        st.write("Orchestration: MCP tools + async agents")
        st.markdown("---")
        st.write(
            "⚠️ LLM calls use free-tier APIs.\n"
            "If you see 429 / quota errors, it just means the daily limit is reached."
        )

        if st.button("Clear chat"):
            st.session_state["chat_history"] = []
            st.success("Chat history cleared.")

    # Tabs
    tab_chat, tab_search, tab_add, tab_orders = st.tabs(
        ["💬 Chat", "🔎 Quick Search", "➕ Add Product", "📦 Orders & Spending"]
    )

    # ===================== TAB 1: CHAT =====================
    with tab_chat:
        st.subheader("Chat with ChemScout")

        # Show history
        for msg in st.session_state["chat_history"]:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                with st.chat_message("user"):
                    st.markdown(content)
            else:
                with st.chat_message("assistant"):
                    st.markdown(content)

        # Chat input
        user_input = st.chat_input("Ask about chemicals, suppliers, orders…")
        if user_input:
            asyncio.run(handle_user_message(user_input))

    # ===================== TAB 2: QUICK SEARCH =====================
    with tab_search:
        st.subheader("Quick Search in Product Database")

        with st.form("search_form"):
            name = st.text_input("Chemical name", placeholder="e.g. Acetone")
            cas = st.text_input("CAS number", placeholder="e.g. 67-64-1")
            supplier = st.text_input("Supplier (optional)", placeholder="e.g. Sigma")
            max_price = st.text_input("Max price (optional, e.g. 50 CHF)")
            submitted = st.form_submit_button("Search")

        if submitted:
            query = (
                "Search the product database for matching chemicals and show "
                "a compact table of results.\n\n"
                f"Name: {name or 'any'}\n"
                f"CAS: {cas or 'any'}\n"
                f"Supplier: {supplier or 'any'}\n"
                f"Max price: {max_price or 'no limit'}"
            )
            asyncio.run(handle_user_message(query))
            st.success("Search request sent (check Chat tab for the answer).")

    # ===================== TAB 3: ADD PRODUCT =====================
    with tab_add:
        st.subheader("Add a New Product")

        with st.form("add_product_form"):
            name = st.text_input("Name", placeholder="Acetone")
            cas = st.text_input("CAS number", placeholder="67-64-1")
            supplier = st.text_input("Supplier", placeholder="Sigma-Aldrich")
            price = st.text_input("Price (numeric)", placeholder="45")
            currency = st.text_input("Currency", value="CHF")
            package = st.text_input("Package size", placeholder="1L")
            purity = st.text_input("Purity", placeholder="99.8%")
            delivery = st.text_input("Delivery time (days)", placeholder="3")
            submitted_add = st.form_submit_button("Add product")

        if submitted_add:
            prompt = (
                "Add a new product to the database with these fields:\n"
                f"- name: {name}\n"
                f"- CAS: {cas}\n"
                f"- supplier: {supplier}\n"
                f"- price: {price} {currency}\n"
                f"- package: {package}\n"
                f"- purity: {purity}\n"
                f"- delivery time (days): {delivery}\n\n"
                "Confirm insertion and show the final stored entry."
            )
            asyncio.run(handle_user_message(prompt))
            st.success("Add-product request sent (see Chat tab for confirmation).")

    # ===================== TAB 4: ORDERS & SPENDING =====================
    with tab_orders:
        st.subheader("Orders & Monthly Spending")

        st.markdown("### Open Orders")
        if st.button("List open orders"):
            prompt = (
                "List all currently open chemical orders from the database. "
                "Show them in a table with product, supplier, quantity, price, and status."
            )
            asyncio.run(handle_user_message(prompt))
            st.info("Request sent (see Chat tab for the result).")

        st.markdown("---")
        st.markdown("### Create a Simple Order")

        with st.form("create_order_form"):
            prod_name = st.text_input("Product name", placeholder="Acetone 99.8% 1L")
            quantity = st.text_input("Quantity", placeholder="3")
            pref_supplier = st.text_input("Preferred supplier (optional)")
            submitted_order = st.form_submit_button("Create order")

        if submitted_order:
            prompt = (
                "Create a new order in the system.\n"
                f"Product: {prod_name}\n"
                f"Quantity: {quantity}\n"
                f"Preferred supplier: {pref_supplier or 'any'}\n"
                "Use the existing product database if possible. "
                "Confirm the created order with an order ID and total price."
            )
            asyncio.run(handle_user_message(prompt))
            st.success("Order creation request sent (see Chat tab for details).")

        st.markdown("---")
        st.markdown("### Monthly Spending Overview")

        with st.form("spending_form"):
            month = st.text_input("Month (1-12)", placeholder="2")
            year = st.text_input("Year", placeholder="2025")
            submitted_spend = st.form_submit_button("Show spending")

        if submitted_spend:
            prompt = (
                "Calculate monthly chemical spending.\n"
                f"Month: {month}\n"
                f"Year: {year}\n"
                "Show the total amount spent and a breakdown per supplier."
            )
            asyncio.run(handle_user_message(prompt))
            st.info("Spending request sent (see Chat tab for the breakdown).")


if __name__ == "__main__":
    main()