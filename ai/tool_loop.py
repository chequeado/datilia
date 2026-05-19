import json
import logging
from typing import Any

from agents import Agent, ModelSettings, Runner
from agents.mcp import MCPServerStreamableHttp
from asgiref.sync import async_to_sync

import ai.llm_client as llm_client  # ensures OPENAI_API_KEY is set in os.environ
from ai.prompts import build_system_prompt
from config import settings

logger = logging.getLogger(__name__)


async def _run_async(
    claim: str,
    context: str | None = None,
    language: str = "es",
    correction: str | None = None,
) -> dict[str, Any]:
    user_message = f"Claim: {claim}"
    if context:
        user_message += f"\n\nBackground text (read-only context to understand the claim above — do NOT verify or investigate anything else mentioned in this text):\n{context}"
    if correction:
        user_message += f"\n\nCorrection request from user (a previous analysis was done — please adjust your research accordingly):\n{correction}"
    if language != "es":
        user_message += f"\n\nPlease respond in: {language}"

    system_prompt = build_system_prompt()
    logger.debug("[tool_loop] user_message=\n%s", user_message)

    async with MCPServerStreamableHttp(
        params={"url": settings.MCP_SERVER_URL},
        cache_tools_list=True,
    ) as mcp_server:
        agent = Agent(
            name="data360-contextualizer",
            instructions=system_prompt,
            mcp_servers=[mcp_server],
            model=llm_client.MODEL,
            model_settings=ModelSettings(temperature=llm_client.TEMPERATURE),
        )
        result = await Runner.run(
            agent,
            input=user_message,
            max_turns=settings.MAX_TOOL_TURNS,
        )

    tool_trace = _extract_tool_trace(result.new_items)
    final_text = result.final_output or ""

    logger.info(
        "[tool_loop] done final_text_len=%d tool_calls=%d",
        len(final_text),
        len(tool_trace),
    )
    return {"final_text": final_text, "tool_trace": tool_trace}


def _extract_tool_trace(items) -> list[dict]:
    """Pair ToolCallItem + ToolCallOutputItem entries into a flat trace list."""
    trace = []
    pending: dict[str, dict] = {}

    for item in items:
        cls = type(item).__name__

        if cls == "ToolCallItem":
            call_id = getattr(item, "call_id", None)
            tool_name = getattr(item, "tool_name", None)
            raw = getattr(item, "raw_item", None)
            # arguments live on raw_item; shape differs by API format
            arguments_str = (
                getattr(raw, "arguments", None)
                or getattr(getattr(raw, "function", None), "arguments", None)
                or "{}"
            )
            try:
                args = json.loads(arguments_str)
            except (json.JSONDecodeError, TypeError):
                args = {}
            if call_id and tool_name:
                pending[call_id] = {"tool": tool_name, "arguments": args, "result": None}

        elif cls == "ToolCallOutputItem":
            call_id = getattr(item, "call_id", None)
            if call_id and call_id in pending:
                pending[call_id]["result"] = getattr(item, "output", None)
                trace.append(pending.pop(call_id))

    return trace


run_agent = async_to_sync(_run_async)
