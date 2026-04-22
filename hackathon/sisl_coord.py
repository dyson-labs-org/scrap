"""WebSocket coordination side-channel for TX/RX role swapping.

Used by --mode call (CoordServer) and --mode respond (CoordClient) when
--coord-port is specified.  Messages are newline-delimited JSON:

    {"type": "ready",    "role": "call"|"respond", "seq": 0}
    {"type": "received", "role": "respond",         "seq": 0}
    {"type": "switch",                              "seq": 0}

The call side runs as WS server in a background thread so the main
synchronous TX/RX path is not blocked.  The respond side connects with
a retry loop and also runs its WS recv in a background thread.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any

import websockets
import websockets.exceptions


def _encode(msg: dict) -> str:
    return json.dumps(msg)


def _decode(raw: Any) -> dict:
    return json.loads(raw)


class CoordServer:
    """WS server side (--mode call). Runs in a background thread."""

    def __init__(self) -> None:
        self._inbox: queue.Queue = queue.Queue()
        self._outbox: queue.Queue = queue.Queue()
        self._loop: asyncio.AbstractEventLoop = None  # type: ignore[assignment]
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self, port: int) -> None:
        """Start WS server in background thread. Returns immediately."""
        self._thread = threading.Thread(
            target=self._run, args=(port,), daemon=True, name="coord-server"
        )
        self._thread.start()
        self._ready.wait(timeout=5)
        print(f"  coord: listening on ws://0.0.0.0:{port}")

    def _run(self, port: int) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve(port))

    async def _serve(self, port: int) -> None:
        async with websockets.serve(self._handler, "0.0.0.0", port):
            self._ready.set()
            # Pump outbox → WS and WS → inbox until closed
            while True:
                await asyncio.sleep(0.05)
                if self._ws is not None:
                    try:
                        msg = self._outbox.get_nowait()
                        await self._ws.send(_encode(msg))
                    except queue.Empty:
                        pass

    async def _handler(self, ws: Any) -> None:
        self._ws = ws
        try:
            async for raw in ws:
                self._inbox.put(_decode(raw))
        except websockets.exceptions.ConnectionClosed:
            pass

    def _recv(self, timeout: float = 120.0) -> dict:
        try:
            return self._inbox.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("coord: timed out waiting for message from respond side")

    def wait_for_ready(self) -> None:
        # Wait until respond side connects (ws is set)
        deadline = time.monotonic() + 120.0
        while self._ws is None:
            if time.monotonic() > deadline:
                raise TimeoutError("coord: respond side never connected")
            time.sleep(0.2)
        msg = self._recv()
        if msg["type"] != "ready":
            raise RuntimeError(f"coord: expected 'ready', got {msg!r}")
        print(f"  coord: respond side ready (seq={msg['seq']})")

    def send_switch(self, seq: int) -> None:
        self._outbox.put({"type": "switch", "seq": seq})
        print(f"  coord: sent switch seq={seq}")

    def wait_for_received(self) -> None:
        msg = self._recv()
        if msg["type"] != "received":
            raise RuntimeError(f"coord: expected 'received', got {msg!r}")
        print(f"  coord: respond confirmed received (seq={msg['seq']})")

    def close(self) -> None:
        pass  # daemon thread exits with process


class CoordClient:
    """WS client side (--mode respond). Runs recv in a background thread."""

    def __init__(self) -> None:
        self._inbox: queue.Queue = queue.Queue()
        self._outbox: queue.Queue = queue.Queue()
        self._loop: asyncio.AbstractEventLoop = None  # type: ignore[assignment]
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()

    def connect(self, host: str, port: int, retry_s: float = 120.0) -> None:
        """Connect to CoordServer with retry. Blocks until connected or timeout."""
        uri = f"ws://{host}:{port}"
        deadline = time.monotonic() + retry_s
        attempt = 0
        while True:
            loop = asyncio.new_event_loop()
            try:
                ws = loop.run_until_complete(
                    websockets.connect(uri, open_timeout=5)
                )
                self._ws = ws
                self._loop = loop
                break
            except (OSError, websockets.exceptions.WebSocketException):
                loop.close()
                attempt += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"coord: could not connect to {uri} after {retry_s:.0f}s"
                    )
                wait = min(2.0, remaining)
                print(f"  coord: waiting for call side ({uri})… attempt {attempt}",
                      flush=True)
                time.sleep(wait)

        print(f"  coord: connected to {uri}")
        # Start background thread to pump messages
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="coord-client"
        )
        self._thread.start()

    def _run(self) -> None:
        self._loop.run_until_complete(self._pump())

    async def _pump(self) -> None:
        try:
            async for raw in self._ws:
                self._inbox.put(_decode(raw))
        except websockets.exceptions.ConnectionClosed:
            pass

    def _send_sync(self, msg: dict) -> None:
        fut = asyncio.run_coroutine_threadsafe(
            self._ws.send(_encode(msg)), self._loop
        )
        fut.result(timeout=10)

    def send_ready(self, seq: int) -> None:
        self._send_sync({"type": "ready", "role": "respond", "seq": seq})
        print(f"  coord: sent ready seq={seq}")

    def send_received(self, seq: int) -> None:
        self._send_sync({"type": "received", "role": "respond", "seq": seq})
        print(f"  coord: sent received seq={seq}")

    def wait_for_switch(self, timeout: float = 300.0) -> None:
        try:
            msg = self._inbox.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("coord: timed out waiting for switch from call side")
        if msg["type"] != "switch":
            raise RuntimeError(f"coord: expected 'switch', got {msg!r}")
        print(f"  coord: received switch seq={msg['seq']}")

    def close(self) -> None:
        pass  # daemon thread exits with process
