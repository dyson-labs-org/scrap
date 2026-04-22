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
import select
import socket
import time

_DIM = "\x1b[2m"
_RESET = "\x1b[0m"


def _sync_msg(msg: str) -> str:
    return f"{_DIM}[sync] {msg}{_RESET}"


class Coord:
    """Half-duplex coordination channel.  Single-threaded send/recv over TCP.

    NOT thread-safe — all send/recv must be from the same thread.
    Use `fileno` property for select()-based readability checks from
    other code (e.g., live_rx_decode stop condition).
    """

    def __init__(self, conn: socket.socket) -> None:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, 'TCP_KEEPIDLE'):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        self._conn = conn
        self._buf = b""

    @property
    def fileno(self) -> int:
        """Socket fd for select() readability checks."""
        return self._conn.fileno()

    def _send(self, msg: dict) -> None:
        self._conn.sendall((json.dumps(msg) + "\n").encode())

    def _recv(self, timeout: float) -> dict:
        """Read one newline-delimited JSON message.  Raises TimeoutError."""
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("coord: timed out waiting for peer")
            if not self._fill_buf(timeout=remaining):
                raise TimeoutError("coord: timed out waiting for peer")
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line)

    def _fill_buf(self, timeout: float) -> bool:
        """Try to read bytes into internal buffer.

        Returns True if bytes were read, False on timeout.
        """
        if timeout < 0:
            timeout = 0.0
        ready, _, _ = select.select([self._conn], [], [], timeout)
        if not ready:
            return False
        chunk = self._conn.recv(4096)
        if not chunk:
            raise ConnectionError("coord: peer disconnected")
        self._buf += chunk
        return True

    def has_data(self) -> bool:
        """Non-blocking check for pending coord bytes/message.

        May read from the socket into the internal line buffer, but does not
        consume a framed JSON line from the caller's perspective.
        """
        if b"\n" in self._buf:
            return True
        return self._fill_buf(timeout=0.0)

    def send_ready(self) -> None:
        self._send({"type": "ready"})

    def wait_for_ready(self) -> None:
        msg = self._recv(timeout=120.0)
        if msg["type"] != "ready":
            raise RuntimeError(f"coord: expected 'ready', got {msg!r}")

    def send_switch(self) -> None:
        self._send({"type": "switch"})

    def wait_for_switch(self, timeout: float = 300.0) -> bool:
        """Block until 'switch' received.  Returns True on success.
        With short timeout, does a non-blocking peek (returns False if nothing)."""
        try:
            msg = self._recv(timeout=timeout)
        except TimeoutError:
            return False
        if msg["type"] != "switch":
            raise RuntimeError(f"coord: expected 'switch', got {msg!r}")
        return True


def listen(port: int) -> Coord:
    """Bind, accept one connection, return Coord.  Blocks."""
    srv = socket.create_server(("0.0.0.0", port), reuse_port=True)
    print(_sync_msg(f"listening on tcp://0.0.0.0:{port}"))
    conn, addr = srv.accept()
    srv.close()
    print(_sync_msg(f"peer connected from {addr[0]}:{addr[1]}"))
    return Coord(conn)


def connect(host: str, port: int, retry_s: float = 120.0) -> Coord:
    """Connect with retry, return Coord.  Blocks."""
    deadline = time.monotonic() + retry_s
    attempt = 0
    while True:
        try:
            conn = socket.create_connection((host, port), timeout=5)
            print(_sync_msg(f"connected to tcp://{host}:{port}"))
            return Coord(conn)
        except OSError:
            attempt += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"coord: could not connect to {host}:{port} "
                    f"after {retry_s:.0f}s")
            print(_sync_msg(f"waiting for caller… attempt {attempt}"),
                  flush=True)
            time.sleep(min(2.0, remaining))
