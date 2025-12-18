"""Agent logic for interacting with LLMs + MCP tools."""

import logging
from typing import Any, List

from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types

logger = logging.getLogger(__name__)


class Agent:
    """
    Generic agent that communicates with an LLM and executes MCP tools.

    Correct tool flow (iterative):
    1) LLM responds → may include tool_calls
    2) Tools executed
    3) LLM is called AGAIN using updated chat history
    4) Repeat until no more tool_calls or max iterations reached
    """

    # Maximum tool call iterations to prevent infinite loops
    MAX_TOOL_ITERATIONS = 10

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

        # Get available tools
        tools = await self.tools()

        # Iterative tool calling loop
        # Continue until no more tool calls or max iterations reached
        iteration = 0
        
        while iteration < self.MAX_TOOL_ITERATIONS:
            iteration += 1
            
            # LLM CALL
            try:
                response = await self._backend.generate(
                    chat,
                    tools=tools,
                    **kwargs,
                )
            except Exception as e:
                logger.exception(f"LLM call failed in iteration {iteration}")
                raise

            # Process response choices
            has_tool_calls = False
            
            for choice in response.choices:
                msg = choice.message
                chat.append(msg)
                all_outputs.append(msg)

                # If no tool calls → continue to check if we should break
                if not msg.tool_calls:
                    continue

                has_tool_calls = True

                # -------------------------------------------------
                # TOOL CALL EXECUTION
                # -------------------------------------------------
                for tool_call in msg.tool_calls:
                    tool_name = tool_call.function.name
                    
                    try:
                        tool_outputs = await self._tool_manager(tool_call)
                        
                        # Add tool outputs to chat & output
                        for tmsg in tool_outputs:
                            chat.append(tmsg)
                            all_outputs.append(tmsg)
                    except Exception as e:
                        logger.exception(f"Tool {tool_name} execution failed")
                        # Add error message to chat so LLM knows the tool failed
                        error_msg = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"Error executing tool: {str(e)}"
                        }
                        chat.append(error_msg)
                        all_outputs.append(error_msg)

            # If no tool calls were made in this iteration, we're done
            if not has_tool_calls:
                break
                
            # Clear kwargs after first iteration (e.g., don't repeat special params)
            kwargs = {}
        
        return all_outputs
