# ChemScout AI

ChemScout AI is an intelligent chemical compound analysis and ordering assistant. It leverages a unified agentic architecture powered by LLMs (Gemini 2.5 Flash) to route user queries to specialized agents.

## Features

-   **Intelligent Routing**: Automatically classifies user intent to route queries to the appropriate agent ("Data" or "Order").
-   **Chemical Data Agent**: Retrieves detailed chemical information, safety data, and supplier details using Model Context Protocol (MCP) tools.
-   **Ordering Agent**: Facilitates the procurement process for lab supplies.
-   **Web Interface**: A modern, responsive chat interface for easy interaction.
-   **CLI Support**: A robust command-line interface for direct interaction.

## Prerequisites

-   Python 3.10+
-   A Google Gemini API Key (stored in `.env`)
-   [UV](https://github.com/astral-sh/uv) (optional, strictly for dependency management if preferred)

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
    Create a `.env` file in the root directory and add your Google API key:
    ```env
    GOOGLE_API_KEY=your_api_key_here
    ```

## Usage

### Web Interface (Recommended)

1.  **Start the server:**
    ```bash
    uvicorn server:app --reload
    ```
2.  **Open your browser:**
    Navigate to [http://localhost:8000](http://localhost:8000).

### Command Line Interface

1.  **Run the main script:**
    ```bash
    python main.py
    ```
2.  **Interact:**
    Type your queries directly into the console.
    - Example: _"Find the molecular weight of Caffeine"_
    - Example: _"Order 50g of Sodium Chloride"_

## Architecture

-   **`main.py`**: CLI entry point.
-   **`server.py`**: FastAPI backend for the web interface.
-   **`src/agents`**: logic for specific agents (Data, Order) and the Router.
-   **`src/tools`**: MCP tool definitions.
-   **`chem_scout_ai/common`**: Shared backend utilities.

## License

[License Name]
