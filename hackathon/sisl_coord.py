"""TCP coordination side-channel for TX/RX role swapping.

Used by --mode call (CoordServer) and --mode respond (CoordClient) when
--coord-port is specified.  Messages are newline-delimited JSON:

    {"type": "ready"}
    {"type": "received"}
    {"type": "switch"}

The call side binds a TCP server socket and accepts in a background daemon
thread.  The respond side connects with a retry loop.  All send/recv are
plain blocking calls on the socket — no asyncio required.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any


def _encode(msg: dict) -> bytes:
    return (json.dumps(msg) + "\n").encode()


def _decode(line: str) -> dict:
    return json.loads(line)


class CoordServer:
    """TCP server side (--mode call)."""

    def __init__(self) -> None:
        self._conn: socket.socket | None = None
        self._rfile: Any = None
        self._connected = threading.Event()

    def start(self, port: int) -> None:
        """Bind TCP socket and accept the respond side in a background thread."""
        self._server_sock = socket.create_server(("0.0.0.0", port))
        threading.Thread(target=self._accept, daemon=True,
                         name="coord-accept").start()
        print(f"  coord: listening on tcp://0.0.0.0:{port}")

    def _accept(self) -> None:
        conn, _ = self._server_sock.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._conn = conn
        self._rfile = conn.makefile("r")
        self._connected.set()

    def _send(self, msg: dict) -> None:
        if not self._connected.wait(timeout=5.0):
            raise TimeoutError("coord: respond side never connected (send)")
        assert self._conn is not None
        self._conn.sendall(_encode(msg))

    def _recv(self, timeout: float = 120.0) -> dict:
        if not self._connected.wait(timeout=timeout):
            raise TimeoutError("coord: respond side never connected")
        assert self._conn is not None and self._rfile is not None
        self._conn.settimeout(timeout)
        try:
            line = self._rfile.readline()
        except OSError:
            raise TimeoutError("coord: timed out waiting for message from respond side")
        finally:
            self._conn.settimeout(None)
        if not line:
            raise ConnectionError("coord: respond side disconnected")
        return _decode(line)

    def wait_for_ready(self) -> None:
        msg = self._recv()
        if msg["type"] != "ready":
            raise RuntimeError(f"coord: expected 'ready', got {msg!r}")
        print(f"  coord: respond side ready")

    def send_switch(self) -> None:
        self._send({"type": "switch"})
        print(f"  coord: sent switch — respond now TX")

    def wait_for_received(self) -> None:
        msg = self._recv()
        if msg["type"] != "received":
            raise RuntimeError(f"coord: expected 'received', got {msg!r}")
        print(f"  coord: respond confirmed received")

    def wait_for_received_async(self) -> threading.Event:
        """Spawn background thread waiting for 'received'; return the Event."""
        ev = threading.Event()
        def _run() -> None:
            self.wait_for_received()
            ev.set()
        threading.Thread(target=_run, daemon=True,
                         name="coord-wait-received").start()
        return ev


class CoordClient:
    """TCP client side (--mode respond)."""

    def __init__(self) -> None:
        self._conn: socket.socket | None = None
        self._rfile: Any = None

    def connect(self, host: str, port: int, retry_s: float = 120.0) -> None:
        """Connect to CoordServer with retry. Blocks until connected or timeout."""
        addr = f"tcp://{host}:{port}"
        deadline = time.monotonic() + retry_s
        attempt = 0
        while True:
            try:
                conn = socket.create_connection((host, port), timeout=5)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._conn = conn
                self._rfile = conn.makefile("r")
                break
            except OSError:
                attempt += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"coord: could not connect to {addr} after {retry_s:.0f}s"
                    )
                print(f"  coord: waiting for call side ({addr})… attempt {attempt}",
                      flush=True)
                time.sleep(min(2.0, remaining))
        print(f"  coord: connected to {addr}")

    def _send(self, msg: dict) -> None:
        assert self._conn is not None
        self._conn.sendall(_encode(msg))

    def _recv(self, timeout: float = 300.0) -> dict:
        assert self._conn is not None and self._rfile is not None
        self._conn.settimeout(timeout)
        try:
            line = self._rfile.readline()
        except OSError:
            raise TimeoutError("coord: timed out waiting for message from call side")
        finally:
            self._conn.settimeout(None)
        if not line:
            raise ConnectionError("coord: call side disconnected")
        return _decode(line)

    def send_ready(self) -> None:
        self._send({"type": "ready"})
        print(f"  coord: sent ready")

    def send_received(self) -> None:
        self._send({"type": "received"})
        print(f"  coord: sent received — waiting for switch")

    def wait_for_switch(self) -> None:
        msg = self._recv()
        if msg["type"] != "switch":
            raise RuntimeError(f"coord: expected 'switch', got {msg!r}")
        print(f"  coord: received switch — starting TX")
