from __future__ import annotations

import asyncio
import json
import time


async def start_health_server(port: int, daemon_state: dict) -> asyncio.Server:
    """Start a minimal HTTP health-check server on the given port."""

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Read the request line
        await reader.readline()
        # Drain headers
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        body = json.dumps(
            {
                "status": "ok",
                "uptime_s": round(time.monotonic() - daemon_state["started_at"], 1),
                "automations_loaded": daemon_state.get("automations_count", 0),
            }
        )
        response = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{body}"
        )
        writer.write(response.encode())
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_handle, "0.0.0.0", port)
    return server
