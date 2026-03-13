from __future__ import annotations

import asyncio
import json
import time

from autopilot.health import start_health_server


class TestHealthServer:
    async def test_returns_json(self):
        state = {"started_at": time.monotonic(), "automations_count": 3}
        server = await start_health_server(0, state)  # port 0 = random available port

        # Get the actual port
        sockets = server.sockets
        port = sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await reader.read(4096)
            writer.close()

            body_start = response.find(b"\r\n\r\n") + 4
            body = json.loads(response[body_start:])

            assert body["status"] == "ok"
            assert body["automations_loaded"] == 3
            assert isinstance(body["uptime_s"], float)
        finally:
            server.close()
            await server.wait_closed()
