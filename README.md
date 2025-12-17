# Devops-LLM-Chemscout

# ChemScout AI

ChemScout AI is an intelligent, agent-based system designed to support chemical reagent procurement by automating data management, supplier comparison, and decision support.  
The system combines large language models (LLMs), a modular agent architecture, and a local database to help users search, manage, and evaluate chemical products efficiently.

The project is built as a backend-first application with a command-line interface and optional UI extensions, focusing on clean architecture, reproducibility, and extensibility.

---

## 1. Project Motivation

Chemical procurement in research and industrial settings is often:
- Time-consuming
- Fragmented across multiple suppliers
- Prone to suboptimal decisions due to price, purity, and availability trade-offs

ChemScout AI addresses this by:
- Centralizing chemical product data
- Providing structured search and comparison
- Enabling automated reasoning via LLM-powered agents
- Supporting reproducible, auditable workflows

---

## 2. Architecture Overview

The system follows a modular architecture:

- **Agents**  
  - Data agent: manages chemical products and queries  
  - Order agent: handles orders and spending analysis  
  - Router: classifies user intent and routes requests to the correct agent  

- **LLM Backend**  
  - Abstracted backend layer (OpenAI / Gemini compatible)
  - Async-first design with rate limiting support

- **MCP Tool Layer**  
  - Tools exposed via MCP (Model Context Protocol)
  - Enables structured tool calls from LLMs

- **Database**  
  - Local SQLite database
  - Stores chemicals, suppliers, and orders

- **Interfaces**
  - CLI chat interface (default)
  - Optional Streamlit UI (experimental)

---

## 3. Repository Structure

##```text##
.
├── main.py                     # Entry point (CLI application)
├── environment.yaml             # Conda environment (dependencies)
├── README.md                    # Project documentation
├── data/
│   └── chem_scout.db            # Local SQLite database
├── chem_scout_ai/
│   └── common/                  # Core abstractions (agent, backend, chat)
├── src/
│   ├── agents/                  # Agent logic and prompts
│   ├── tools/                   # MCP tools
│   ├── database/                # Database access layer
│   ├── interfaces/              # CLI / UI interfaces
│   ├── mcp/                     # MCP server
│   └── utils/                   # Logging and helpers

---

## 4. Environment Setup

All dependencies are defined in **`environment.yaml`**, which replaces `requirements.txt` and serves as the **single source of truth** for installing and running the project.

### Create the Conda environment

##```bash##
conda env create -f environment.yaml
conda activate chem-scout-ai


---


### 5. API Keys
##```md##
## API Keys

ChemScout AI requires an API key for a supported LLM backend.

Create a `.env` file in the project root:

## ```env
OPENAI_API_KEY=your_openai_key_here
# or
GOOGLE_API_KEY=your_gemini_key_here

### 6. Running the Application
##```md
## Running the Application

Start the application via the command line:

##```bash
python main.py

### 7. Optional: Streamlit UI
##```md
## Optional: Streamlit UI

An experimental Streamlit-based UI is included for interactive exploration.

##```bash
streamlit run streamlit_app.py

### 8. Limitations
##```md
## Limitations

- Supplier data is limited to available tool integrations
- LLM usage depends on external API quotas
- Web scraping is not enabled by default

## Conclusion

ChemScout AI demonstrates how LLM-driven agents and modern DevOps practices
can be combined to automate complex procurement workflows in a reproducible
and modular way.
