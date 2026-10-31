from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..core import config


def _kit_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "services" / "travel_mcp.py").is_file():
            return parent
        if (parent / "kit" / "services" / "travel_mcp.py").is_file():
            return parent / "kit"
    raise RuntimeError("Could not locate the kit services (services/travel_mcp.py).")


@asynccontextmanager
async def connection():
    env = dict(os.environ)
    env.update(TRAVEL_API_URL=config.TRAVEL_API_URL, TRAVEL_API_KEY=config.TRAVEL_API_KEY)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "services.travel_mcp"],
        cwd=str(_kit_root()),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> dict:
    response = await session.call_tool(name, arguments)
    if response.isError:
        raise RuntimeError(f"MCP tool {name} failed")
    structured = response.structuredContent
    if isinstance(structured, dict):
        data = structured.get("result", structured)
    elif response.content:
        data = json.loads(response.content[0].text)
        data = data.get("result", data) if isinstance(data, dict) else {}
    else:
        data = {}
    if not isinstance(data, dict) or not data.get("ok", False):
        err = data.get("error", {}) if isinstance(data, dict) else {}
        raise RuntimeError(err.get("message", f"MCP tool {name} failed"))
    return data
