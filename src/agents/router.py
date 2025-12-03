# src/agents/router.py

from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types


INTENT_SYSTEM_PROMPT = """
You are an intent-classification model for ChemScout AI.

Your output must be exactly one of the following labels:
- "data"  → when the user wants information extraction, supplier comparison,
            database lookup, product parsing, or updating stored chemical data.
- "order" → when the user wants to buy, order, reorder, confirm an order,
            check order status, or select products to purchase.

If unclear:
- Choose "data" unless the user explicitly expresses a desire to place an order.

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
