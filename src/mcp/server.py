from mcp.server import FastMCP

# Dies ist unser MCP Server
SERVER = FastMCP()

# Wir importieren deine Tool-Definitionen
# → Dadurch werden automatisch alle Tools bei SERVER registriert
import src.tools.chem_scout_mcp_tools  # noqa: F401


def start_server(host: str = "localhost", port: int = 8765):
    """
    Blocking Start des MCP Servers (für Tests oder manuelle Nutzung).
    """
    SERVER.run(host=host, port=port)


async def start_server_async(host: str = "localhost", port: int = 8765):
    """
    Async Start des MCP Servers (für main.py Option 3).
    """
    await SERVER.run(host=host, port=port)
