# src/agents/router.py

from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types


INTENT_SYSTEM_PROMPT = """
You are an intent-classification model for ChemScout AI.

Your output must be exactly one of the following labels:
- "data"  → when the user wants information extraction, supplier comparison,
            database lookup, product parsing, updating stored chemical data,
            OR processing inventory corrections/alerts.
- "order" → when the user wants to buy, order, reorder, confirm an order,
            check order status, view notifications, or select products to purchase.

ALWAYS classify as "data" when ANY of these appear:
- "inventory_correction" or "inventory correction"
- "process inventory" or "process alert"
- "update inventory" or "revise inventory"
- "reduce quantity" or "adjust stock"
- Requests from the Order Agent to update inventory
- Messages containing "please revise remaining quantity"

ALWAYS classify as "order" when ANY of these appear:
- "AUTOMATED ORDER REQUEST"
- "Create order" or "create an order"
- "place an order" or "place order"
- "buy", "purchase", "reorder"
- "REQUIRED ACTIONS" with order-related steps
- quantity + chemical name (e.g., "500 g", "1 L") with purchase intent
- "order for [chemical name]"
- "show notifications" or "sent emails"

If unclear:
- Choose "data" unless the user expresses any desire to place an order.

Output format:
Just the label, nothing else.
"""


async def classify_intent(user_input: str, backend) -> str:
    """
    Uses the LLM backend to decide whether the intent is:
    - "data"
    - "order"
    """

    # Temporary chat
    temp_chat = chat_lib.Chat(
        messages=[
            types.SystemMessage(role="system", content=INTENT_SYSTEM_PROMPT),
            types.UserMessage(role="user", content=user_input),
        ]
    )

    # ---- FIX: use backend.generate(chat) positional ----
    result = await backend.generate(
        temp_chat,
        max_tokens=4,
        temperature=0.0,
    )

    # ---- FIX: extract content using OpenAI-style structure ----
    # result.choices[0].message.content
    try:
        content = result.choices[0].message.content.strip().lower()
    except Exception:
        return "data"   # fail-safe fallback

    if content not in ("data", "order"):
        return "data"

    return content
