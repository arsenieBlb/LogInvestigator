"""Actual official-SDK client with a tightly scoped subprocess environment."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.types import TextContent

TOOL_NAMES = frozenset({"search_logs", "get_event", "trace_request", "search_known_issues"})


class DiagnosticClient:
    def __init__(self, client: Client):
        self.client = client

    async def list_tools(self) -> list[str]:
        listed = await self.client.list_tools()
        return [tool.name for tool in listed.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            return {
                "error": {
                    "code": "unknown_tool",
                    "message": "tool is outside the diagnostic capability allow-list",
                }
            }
        result = await self.client.call_tool(name, arguments)
        if result.is_error:
            detail = " ".join(
                block.text for block in result.content if isinstance(block, TextContent)
            )
            return {"error": {"code": "invalid_tool_call", "message": detail[:512]}}
        if result.structured_content is not None:
            return dict(result.structured_content)
        for block in result.content:
            if isinstance(block, TextContent):
                decoded = json.loads(block.text)
                if isinstance(decoded, dict):
                    return decoded
        return {
            "error": {
                "code": "invalid_response",
                "message": "server returned no structured diagnostic response",
            }
        }


def server_parameters(db_path: str | Path) -> StdioServerParameters:
    # The SDK adds its OS bootstrap allow-list, never the parent's arbitrary keys.
    environment = {
        name: os.environ[name]
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if name in os.environ
    }
    environment["PYTHONUNBUFFERED"] = "1"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "log_investigator.mcp_server", "--db", str(Path(db_path).resolve())],
        env=environment,
    )


@asynccontextmanager
async def diagnostic_session(db_path: str | Path) -> AsyncIterator[DiagnosticClient]:
    """Spawn a server and negotiate MCP; context exit shuts down the child."""
    async with Client(server_parameters(db_path)) as client:
        yield DiagnosticClient(client)
