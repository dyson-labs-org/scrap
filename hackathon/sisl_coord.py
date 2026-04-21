"""WebSocket coordination side-channel for TX/RX role swapping.

Used by --mode call (CoordServer) and --mode respond (CoordClient) when
--coord-port is specified.  Messages are newline-delimited JSON:

    {"type": "ready",    "role": "call"|"respond", "seq": 0}
    {"type": "received", "role": "respond",         "seq": 0}
    {"type": "switch",                              "seq": 0}

The call side runs as WS server; respond side connects as client.
One connection, no reconnect logic — this is a local hackathon demo.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import websockets
import websockets.exceptions


def _encode(msg: dict) -> str:
    return json.dumps(msg)


def _decode(raw: Any) -> dict:
    return json.loads(raw)


class CoordServer:
    """WS server side (--mode call). Listens, accepts one client."""

    def __init__(self) -> None:
        self._ws: Any = None
        self._server: Any = None
        self._inbox: asyncio.Queue = asyncio.Queue()

    async def start(self, port: int) -> None:
        self._server = await websockets.serve(
            self._handler, "0.0.0.0", port
        )
        print(f"  coord: listening on ws://0.0.0.0:{port}")

    async def _handler(self, ws: Any) -> None:
        self._ws = ws
        try:
            async for raw in ws:
                await self._inbox.put(_decode(raw))
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _recv(self) -> dict:
        while self._ws is None:
            await asyncio.sleep(0.05)
        return await self._inbox.get()

    async def wait_for_ready(self) -> None:
        msg = await self._recv()
        assert msg["type"] == "ready", f"unexpected: {msg}"
        print(f"  coord: respond side ready (seq={msg['seq']})")

    async def send_switch(self, seq: int) -> None:
        assert self._ws is not None
        await self._ws.send(_encode({"type": "switch", "seq": seq}))
        print(f"  coord: sent switch seq={seq}")

    async def wait_for_received(self) -> None:
        msg = await self._recv()
        assert msg["type"] == "received", f"unexpected: {msg}"
        print(f"  coord: respond confirmed received (seq={msg['seq']})")

    def close(self) -> None:
        if self._server is not None:
            self._server.close()


class CoordClient:
    """WS client side (--mode respond). Connects to CoordServer."""

    def __init__(self) -> None:
        self._ws: Any = None

    async def connect(self, host: str, port: int) -> None:
        uri = f"ws://{host}:{port}"
        self._ws = await websockets.connect(uri)
        print(f"  coord: connected to {uri}")

    async def send_ready(self, seq: int) -> None:
        await self._ws.send(_encode({"type": "ready", "role": "respond", "seq": seq}))
        print(f"  coord: sent ready seq={seq}")

    async def send_received(self, seq: int) -> None:
        await self._ws.send(_encode({"type": "received", "role": "respond", "seq": seq}))
        print(f"  coord: sent received seq={seq}")

    async def wait_for_switch(self) -> None:
        msg = _decode(await self._ws.recv())
        assert msg["type"] == "switch", f"unexpected: {msg}"
        print(f"  coord: received switch seq={msg['seq']}")

    def close(self) -> None:
        if self._ws is None:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._ws.close())
        except RuntimeError:
            asyncio.run(self._ws.close())
