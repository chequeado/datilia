# Adapted from worldbank/data-ai-chatbot (Apache-2.0). Original copyright (c) World Bank Group AI for Data team.
import logging
from functools import cache

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from asgiref.sync import async_to_sync

from config import settings

logger = logging.getLogger(__name__)


@cache
def _get_transport() -> StreamableHttpTransport:
    return StreamableHttpTransport(
        url=settings.MCP_SERVER_URL,
        httpx_client_factory=_make_httpx_client,
    )


def _make_httpx_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    **kwargs,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout or httpx.Timeout(settings.REQUEST_TIMEOUT_SECONDS),
        auth=auth,
        **kwargs,
    )


async def _read_resource_async(uri: str) -> str:
    """Fetch a text resource from the MCP server (e.g. data360://system-prompt)."""
    async with Client(_get_transport()) as client:
        resources = await client.read_resource(uri)

    if not resources:
        return ""
    content = resources[0]
    return getattr(content, "text", "") or ""


read_resource: "(uri: str) -> str" = async_to_sync(_read_resource_async)

