"""Agent logic for interacting with LLMs + MCP tools."""

from typing import Any, List

from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types


class Agent:
    """
    Generic agent that communicates with an LLM and executes MCP tools.

    Correct tool flow:
    1) LLM responds → may include tool_calls
    2) Tools executed
    3) LLM is called AGAIN using updated chat history
    """

    def __init__(self, backend, tool_manager=None) -> None:
        self._backend = backend
        self._tool_manager = tool_manager

    # -------------------------------------------------------------
    async def tools(self) -> list[types.Tool]:
        if not self._tool_manager:
            return []
        return await self._tool_manager.tools()

    # -------------------------------------------------------------
    async def __call__(
        self,
        *,
        chat: chat_lib.Chat,
        **kwargs: Any,
    ) -> List[types.Message]:

        all_outputs: List[types.Message] = []

        # 1) get available tools
        tools = await self.tools()

        # ---------------------------------------------------------
        # FIRST LLM CALL
        # ---------------------------------------------------------
        response = await self._backend.generate(
            chat,
            tools=tools,
            **kwargs,
        )

        for choice in response.choices:
            msg = choice.message
            chat.append(msg)
            all_outputs.append(msg)

            # If no tool calls → normal assistant message
            if not msg.tool_calls:
                continue

            # -----------------------------------------------------
            # TOOL CALL EXECUTION
            # -----------------------------------------------------
            for tool_call in msg.tool_calls:
                tool_outputs = await self._tool_manager(tool_call)

                # add tool outputs to chat & output
                for tmsg in tool_outputs:
                    chat.append(tmsg)
                    all_outputs.append(tmsg)

            # -----------------------------------------------------
            # SECOND LLM CALL (AFTER TOOL OUTPUT)
            # -----------------------------------------------------
            second = await self._backend.generate(
                chat,
                tools=tools,
            )

            for choice2 in second.choices:
                msg2 = choice2.message
                chat.append(msg2)
                all_outputs.append(msg2)

        return all_outputs
