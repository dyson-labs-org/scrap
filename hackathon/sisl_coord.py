"""TCP coordination side-channel for half-duplex TX/RX role swapping.

Test harness for HackRF (half-duplex hardware).  Two message types:

    {"type": "ready"}     respond → call at startup
    {"type": "switch"}    either side, after finishing a TX or RX phase

Usage:
    --coord 0.0.0.0:4574      listen (call side)
    --coord 192.168.1.X:4574   connect (respond side)

All calls are blocking.  No background threads.  No asyncio.
"""

from __future__ import annotations

import json
import socket
import time


def _send(conn: socket.socket, msg: dict) -> None:
    conn.sendall((json.dumps(msg) + "\n").encode())


def _recv(conn: socket.socket, rfile, timeout: float = 300.0) -> dict:
    conn.settimeout(timeout)
    try:
        line = rfile.readline()
    except OSError:
        raise TimeoutError("coord: timed out waiting for peer")
    finally:
        conn.settimeout(None)
    if not line:
        raise ConnectionError("coord: peer disconnected")
    return json.loads(line)


class Coord:
    """Half-duplex coordination channel.  Blocking send/recv over TCP."""

    def __init__(self, conn: socket.socket) -> None:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._conn = conn
        self._rfile = conn.makefile("r")

    def send_ready(self) -> None:
        _send(self._conn, {"type": "ready"})
        print("  coord: sent ready", flush=True)

    def wait_for_ready(self) -> None:
        msg = _recv(self._conn, self._rfile, timeout=120.0)
        if msg["type"] != "ready":
            raise RuntimeError(f"coord: expected 'ready', got {msg!r}")
        print("  coord: respond side ready", flush=True)

    def send_switch(self) -> None:
        _send(self._conn, {"type": "switch"})
        print("  coord: sent switch", flush=True)

    def wait_for_switch(self) -> None:
        msg = _recv(self._conn, self._rfile)
        if msg["type"] != "switch":
            raise RuntimeError(f"coord: expected 'switch', got {msg!r}")
        print("  coord: received switch", flush=True)


def listen(port: int) -> Coord:
    """Bind, accept one connection, return Coord.  Blocks."""
    srv = socket.create_server(("0.0.0.0", port), reuse_port=True)
    print(f"  coord: listening on tcp://0.0.0.0:{port}")
    conn, addr = srv.accept()
    srv.close()
    print(f"  coord: accepted connection from {addr[0]}:{addr[1]}")
    return Coord(conn)


def connect(host: str, port: int, retry_s: float = 120.0) -> Coord:
    """Connect with retry, return Coord.  Blocks."""
    deadline = time.monotonic() + retry_s
    attempt = 0
    while True:
        try:
            conn = socket.create_connection((host, port), timeout=5)
            print(f"  coord: connected to tcp://{host}:{port}")
            return Coord(conn)
        except OSError:
            attempt += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"coord: could not connect to {host}:{port} "
                    f"after {retry_s:.0f}s")
            print(f"  coord: waiting for call side… attempt {attempt}",
                  flush=True)
            time.sleep(min(2.0, remaining))
