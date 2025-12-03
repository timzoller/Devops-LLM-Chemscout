"""Provides MCP tool integration for the agent system (HTTP version for FastMCP)."""

import contextlib
import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

import mcp
from mcp import types as mcp_types
from mcp.client import streamable_http

from chem_scout_ai.common import types


# -------------------------------------------------------------------------
# MCP Session Handling (streamable-http)
# -------------------------------------------------------------------------

ClientSession = mcp.ClientSession
ClientSessionFactory = Callable[
    [], contextlib.AbstractAsyncContextManager[mcp.ClientSession]
]


@contextlib.asynccontextmanager
async def mcp_session(
    url: str,
    *,
    authorization: str | None = None,
) -> AsyncGenerator[mcp.ClientSession, None]:
    """Creates a streamable-http MCP session."""

    headers = {}
    if authorization:
        headers["Authorization"] = f"Bearer {authorization}"

    async with streamable_http.streamablehttp_client(url, headers=headers) as (
        read_stream,
        write_stream,
        _,
    ), mcp.ClientSession(read_stream, write_stream) as session:

        await session.initialize()
        yield session


def mcp_session_factory(url: str, **kwargs: Any) -> ClientSessionFactory:
    return lambda: mcp_session(url, **kwargs)


# -------------------------------------------------------------------------
# Tool Manager
# -------------------------------------------------------------------------

class ToolManager:
    """Manages MCP tools for LLM-driven tool calls."""

    def __init__(
        self,
        session_factory: ClientSessionFactory,
        allowed_tools: set[str] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._allowed_tools = allowed_tools

    async def available_tools(self) -> list[types.Tool]:
        async with self._session_factory() as session:
            resp = await session.list_tools()
            return [tool_from_mcp(t) for t in resp.tools]

    async def tools(self) -> list[types.Tool]:
        tools = await self.available_tools()

        if self._allowed_tools:
            tools = [
                t
                for t in tools
                if t["function"]["name"] in self._allowed_tools
            ]

        return tools

    async def __call__(
        self,
        tool_call: types.ToolCall,
    ) -> list[dict]:

        tool_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        # whitelist check → MUST RETURN DICT ONLY
        if (
            self._allowed_tools is not None
            and tool_name not in self._allowed_tools
        ):
            return [{
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": f"Tool '{tool_name}' not allowed.",
            }]

        async with self._session_factory() as session:
            result = await session.call_tool(tool_name, args)

            return [
                tool_call_result_from_mcp(tool_call.id, content)
                for content in result.content
            ]


    @classmethod
    def from_url(
        cls,
        url: str,
        allowed_tools: set[str] | None = None,
        **kwargs: Any,
    ):
        return cls(
            session_factory=mcp_session_factory(url, **kwargs),
            allowed_tools=allowed_tools,
        )


# -------------------------------------------------------------------------
# Conversion helpers
# -------------------------------------------------------------------------

def tool_from_mcp(tool: mcp_types.Tool) -> types.Tool:
    return types.Tool(
        type="function",
        function=types.Function(
            name=tool.name,
            description=tool.description,
            parameters=tool.inputSchema,
            strict=True,
        ),
    )


def tool_call_result_from_mcp(call_id: str, content: mcp_types.ContentBlock) -> dict:

    if content.type == "text":
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": content.text,
        }

    if content.type == "resource":
        mime = content.resource.mimeType.split(";")[0]
        if mime == "text/plain":
            return {
                "role": "tool",
                "tool_call_id": call_id,
                "content": content.resource.text,
            }
        raise ValueError(f"Unsupported MIME type: {mime}")

    raise ValueError(f"Unknown content type: {content.type}")
