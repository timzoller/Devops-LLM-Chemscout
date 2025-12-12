
import asyncio
import threading
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load env vars immediatey
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import uvicorn

from chem_scout_ai.common.backend import Gemini2p5Flash
from chem_scout_ai.common import types
from src.utils.logger import get_logger
from src.tools.chem_scout_mcp_tools import SERVER
from src.agents.router import classify_intent
from src.agents.factory import build_agents
from src.database.db import (
    init_db,
    log_search,
    get_search_history,
    get_inventory_stats,
    get_order_history_stats,
    list_all_products
)

logger = get_logger(__name__)

# --- Global State ---
agents_map = {}
backend = None

# --- Background MCP Server ---
def _run_mcp():
    uvicorn.run(
        SERVER.streamable_http_app,
        host="127.0.0.1",
        port=8011, # Using 8011 to avoid conflict if main API is on 8010
        log_level="error"
    )

def start_mcp_background():
    thread = threading.Thread(target=_run_mcp, daemon=True)
    thread.start()
    logger.info("MCP server started in background on http://127.0.0.1:8011/mcp")
    return thread

# --- Lifespan for Startup/Shutdown ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global agents_map, backend

    print("\n=== ChemScout AI Backend Starting ===\n")
    
    # 1. Init DB
    init_db()
    logger.info("Database initialized.")

    # 2. Start MCP server (using a different port than main app usually)
    # Note: main.py used 8000. If we run this app on 8000, we need MCP on another port?
    # actually main.py ran MCP on 8000. 
    # Let's run THIS API on 8000 and MCP on 8001 to avoid conflict since they are both uvicorn.
    # OR run them in same process? No, MCP tools uses SERVER.streamable_http_app which is an SSE app.
    # We can mount it? 
    # For simplicity, let's keep the pattern from main.py: background thread for MCP.
    start_mcp_background()
    await asyncio.sleep(1.0) 

    # 3. Init Backend
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GOOGLE_API_KEY not found in environment. Chat features will not work.")
        backend = None
    else:
        try:
            backend = Gemini2p5Flash(api_key=api_key).get_async_backend()
            logger.info("Backend initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize backend: {e}")
            backend = None

    # 4. Build Agents
    if backend:
        try:
            agents_map = build_agents(backend)
            logger.info("Agents built.")
        except Exception as e:
            logger.exception("Failed to build agents")
    else:
        logger.warning("Skipping agent build due to missing backend.")
    
    yield
    
    print("\n=== ChemScout AI Backend Shutting Down ===\n")

app = FastAPI(lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    messages: list[str]

# --- Endpoints ---

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    user_text = req.message.strip()
    if not user_text:
        return ChatResponse(messages=[])

    try:
        if not backend or not agents_map:
             return ChatResponse(messages=["system: Error - Backend not initialized. Please check GOOGLE_API_KEY in .env file."])

        # 1. Classify Intent
        try:
            intent = await classify_intent(user_text, backend)
            logger.info(f"Router selected agent: {intent}")
        except Exception as e:
            logger.warning(f"Intent classification failed: {e}. Defaulting to 'data'.")
            intent = "data"
        
        # 2. Get Agent
        if intent not in agents_map:
             logger.warning(f"Unknown intent {intent}, defaulting to data")
             intent = "data"
        
        agent, chat = agents_map[intent]

        # 3. Append User Message
        chat.append(types.UserMessage(role="user", content=user_text))
        
        # 3.1 Log Search Query
        try:
             log_search(user_text)
        except Exception as e:
             logger.error(f"Failed to log search: {e}")

        # 4. Run Agent
        # Note: agent(chat=chat) returns list of responses
        responses = await agent(chat=chat)

        # 5. Extract text for frontend
        output_messages = []
        for msg in responses:
            # Determine role and content safely
            role = "assistant"
            if hasattr(msg, "role"):
                role = msg.role
            elif isinstance(msg, dict):
                role = msg.get("role", "assistant")
            
            content = ""
            if hasattr(msg, "content"):
                content = msg.content
            elif isinstance(msg, dict):
                content = msg.get("content", "")

            # Filter logic:
            # 1. Skip tool outputs (role="tool")
            # 2. Skip system messages (role="system")
            # 3. Only show assistant messages with actual text content
            if role == "assistant" and content:
                output_messages.append(str(content))

        return ChatResponse(messages=output_messages)

    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        error_msg = "⚠️ I'm having trouble connecting to the backend. "
        
        # Check for Rate Limit specifically
        error_str = str(e)
        if "429" in error_str or "RateLimit" in type(e).__name__:
            error_msg = "⏳ **Rate Limit Exceeded**\n\nYou have run out of tokens. Please wait a moment before sending another message."
        else:
            error_msg += f"\nError details: {error_str}"
            
        return ChatResponse(messages=[error_msg])

@app.get("/api/dashboard/stats")
async def get_stats():
    try:
        data = get_inventory_stats()
        # Add order history
        data["order_history"] = get_order_history_stats()
        return data
    except Exception as e:
        logger.exception("Error fetching stats")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dashboard/history")
async def get_history():
    try:
        return get_search_history(limit=50)
    except Exception as e:
        logger.exception("Error fetching history")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/products")
async def get_products():
    try:
        return list_all_products()
    except Exception as e:
         logger.exception("Error fetching products")
         raise HTTPException(status_code=500, detail=str(e))

# Mount static files – MUST be last to avoid catching API routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
