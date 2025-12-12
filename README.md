# ChemScout AI

ChemScout AI is an intelligent assistant for chemical compound analysis and lab management. It uses a sophisticated agentic architecture powered by **Google Gemini 2.5 Flash** to understand user intent and perform complex tasks through a unified chat interface.

## Features

-   **🧠 Intelligent Routing**: Automatically routes queries to specialized sub-agents:
    -   **Data Agent**: Fetches chemical properties, safety info, and supplier data via MCP tools.
    -   **Order Agent**: Handles inventory checks and facilitates ordering lab supplies.
-   **💬 Modern Chat Interface**: A clean, glassmorphism-styled web UI aimed at distractions-free productivity.
-   **🔌 MCP Integration**: Uses the Model Context Protocol to seamlessly connect LLMs with external data sources.
-   **🛡️ Robust Error Handling**: Gracefully manages API rate limits and connection issues.

## Prerequisites

-   **Python 3.10+**
-   A **Google Gemini API Key** (Get one at [aistudio.google.com](https://aistudio.google.com/))

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd Devops-LLM-Chemscout
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment:**
    Create a `.env` file in the root directory (copy from `.env.example` if available) and add your key:
    ```env
    GOOGLE_API_KEY=your_gemini_api_key_here
    ```

## Usage

### Start the Web Application
This is the primary way to use ChemScout AI.

1.  **Run the server:**
    ```bash
    python server.py
    ```
    *(This automatically starts both the FastAPI backend and the background MCP server)*

2.  **Open in Browser:**
    Go to **[http://localhost:8000](http://localhost:8000)**

3.  **Start Chatting:**
    -   *"What is the CAS number for Caffeine?"*
    -   *"Do we have any Acetone in stock?"*
    -   *"Show me the safety data for Sulfuric Acid."*

### Troubleshooting
-   **Rate Limit Exceeded**: If the chat replies with "You have run out of tokens", simply wait about 60 seconds for the free tier quota to reset.
-   **Port Conflicts**: If the server fails to start, ensure ports `8000` and `8011` are free.

## Architecture

-   **Frontend**: HTML5, Vanilla JS, CSS (Glassmorphism design).
-   **Backend**: FastAPI (`server.py`) serving the REST API and static files.
-   **AI Core**: Google Gemini 2.5 Flash via `google-generativeai`.
-   **Tools**: Custom MCP tools for chemical database lookups and inventory management.

## Project Structure

```
├── chem_scout_ai/      # Core AI logic & backend wrappers
├── src/
│   ├── agents/         # Router and specific Agent implementations
│   ├── database/       # Local SQLite database for inventory/history
│   └── tools/          # MCP Tool definitions
├── static/             # Web frontend assets (html, css, js)
├── server.py           # Main application entry point
├── main.py             # CLI entry point (legacy)
└── requirements.txt    # Python dependencies
```
