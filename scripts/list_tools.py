"""Start the NINA Advanced MCP server over stdio, list its tools and make read-only calls."""
import asyncio
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

HOST = os.environ.get("NINA_HOST", "192.168.1.211")
PORT = os.environ.get("NINA_PORT", "1888")


async def main():
    transport = StdioTransport(
        command=sys.executable,
        # The package has no __main__.py, so start the server directly.
        args=["-c", "from nina_advanced_mcp import mcp; mcp.run()"],
        env={**os.environ, "NINA_HOST": HOST, "NINA_PORT": PORT, "LOG_LEVEL": "WARNING"},
    )
    async with Client(transport) as client:
        tools = await client.list_tools()
        print(f"{len(tools)} tools")
        for t in tools:
            print(f"- {t.name}")
        # Parameterised tools take their arguments wrapped in an "input" object.
        calls = [
            ("nina_connect", {"input": {}}),
            ("nina_get_version", {"input": {}}),
            ("nina_get_camera_info", {}),
            ("nina_get_mount_info", {}),
            ("nina_get_focuser_info", {}),
        ]
        for name, args in calls:
            result = await client.call_tool(name, args, raise_on_error=False)
            print(f"\n== {name}\n{result.content[0].text[:600]}")


asyncio.run(main())
