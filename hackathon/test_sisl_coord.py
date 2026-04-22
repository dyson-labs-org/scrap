import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sisl_coord import Coord, _sync_msg


def _make_pair() -> tuple[Coord, socket.socket]:
    srv = socket.create_server(("127.0.0.1", 0), reuse_port=True)
    port = srv.getsockname()[1]
    peer = socket.create_connection(("127.0.0.1", port), timeout=1.0)
    conn, _ = srv.accept()
    srv.close()
    return Coord(conn), peer


def test_has_data_does_not_consume_switch_message() -> None:
    coord, peer = _make_pair()
    try:
        peer.sendall(b'{"type":"switch"}\n')
        assert coord.has_data() is True
        assert coord.wait_for_switch(timeout=0.1) is True
    finally:
        peer.close()
        coord._conn.close()


def test_wait_for_switch_short_timeout_preserves_partial_data() -> None:
    coord, peer = _make_pair()
    try:
        peer.sendall(b'{"type":"switch"')
        assert coord.wait_for_switch(timeout=0.01) is False
        peer.sendall(b"}\n")
        assert coord.wait_for_switch(timeout=0.1) is True
    finally:
        peer.close()
        coord._conn.close()


def test_sync_message_format() -> None:
    assert _sync_msg("connected") == "\x1b[2m[sync] connected\x1b[0m"
