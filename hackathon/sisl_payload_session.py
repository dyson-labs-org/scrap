from __future__ import annotations

import os
import struct

from sparse_rlnc import RLNCEncoder, RLNCDecoder
from sisl_payload import encode_payload_symbol, decode_payload_symbol, encode_ack, decode_ack
from sisl_crypto import derive_session_prk


class RLNCSession:
    _ACK_MAX_UNIQUE_TRIALS = 1024

    def __init__(
        self,
        payload: bytes,
        K: int,
        session_keys: dict,
        *,
        max_decode_symbols: int | None = None,
    ):
        self._payload = payload
        self._K = K
        self._session_keys = session_keys
        self._prk = derive_session_prk(session_keys)
        self._session_id = session_keys["session_id"]
        # Directional keys: c2r = caller→responder, r2c = responder→caller.
        # next_tx_frame / rx_frame use _c2r_key (payload flows caller→responder).
        # build_ack / verify_ack use _r2c_key (ACK flows responder→caller).
        self._c2r_key = session_keys["p2p_tx_key"]
        self._r2c_key = session_keys["p2p_rx_key"]
        self._encoder = RLNCEncoder(payload, K, self._prk)
        self._decoder = RLNCDecoder(K, self._prk, max_symbols=max_decode_symbols)
        self._next_comb_id = 0
        self._recovered: bytes | None = None
        self._ack_min_seq = 0
        self._ack_seen_seqs: set[int] = set()
        self._ack_accepted = False

    @classmethod
    def for_responder(cls, recovered_payload: bytes, K: int, session_keys: dict) -> "RLNCSession":
        """Construct a session for the responder side after payload is decoded.

        The responder only decodes RLNC symbols (never encodes), so no
        RLNCEncoder is allocated. _recovered is pre-set so build_ack() works
        without needing to call rx_frame() first.
        """
        inst = object.__new__(cls)
        inst._payload = recovered_payload
        inst._K = K
        inst._session_keys = session_keys
        inst._prk = derive_session_prk(session_keys)
        inst._session_id = session_keys["session_id"]
        inst._c2r_key = session_keys["p2p_tx_key"]
        inst._r2c_key = session_keys["p2p_rx_key"]
        inst._encoder = None
        inst._decoder = RLNCDecoder(K, inst._prk)
        inst._next_comb_id = 0
        inst._recovered = recovered_payload
        inst._ack_min_seq = 0
        inst._ack_seen_seqs = set()
        inst._ack_accepted = False
        return inst

    @staticmethod
    def _ack_debug(msg: str) -> None:
        if os.environ.get("SISL_DEBUG"):
            print(f"  [ACK RX] {msg}", flush=True)

    def reset_tx(self) -> None:
        """Reset the TX comb_id counter so a fresh pass uses new AEAD nonces."""
        self._next_comb_id = 0

    def next_tx_frame(self) -> bytes:
        comb_id = self._next_comb_id
        self._next_comb_id += 1
        _, encoded_bytes, _ = self._encoder.encode_symbol(comb_id)
        return encode_payload_symbol(
            comb_id, encoded_bytes, self._c2r_key, self._prk, self._session_id)

    def rx_frame(self, frame: bytes) -> bool:
        if self._decoder.is_budget_exhausted:
            return False
        comb_id, plain = decode_payload_symbol(
            frame, self._c2r_key, self._prk, self._session_id)
        complete = self._decoder.add_symbol(comb_id, plain)
        if complete and self._recovered is None:
            raw = self._decoder.decode()
            # raw is the full padded block; trim to original payload length.
            self._recovered = raw[: len(self._payload)] if raw is not None else None
        return complete

    def recovered_payload(self) -> bytes | None:
        return self._recovered

    def build_ack(self, seq: int = 0) -> bytes | None:
        assert self._recovered is not None, "build_ack called before decode complete"
        return encode_ack(self._recovered, self._r2c_key, self._prk,
                          self._session_id, seq=seq, K=self._K)

    def verify_ack(self, ack_frame: bytes) -> bool:
        if self._ack_accepted:
            self._ack_debug("reject replay after session ACK already accepted")
            return False
        if len(ack_frame) < 4:
            self._ack_debug(f"reject short ACK frame: {len(ack_frame)} bytes")
            return False
        seq = struct.unpack(">I", ack_frame[:4])[0]
        if seq < self._ack_min_seq:
            self._ack_debug(f"reject stale seq={seq} < min={self._ack_min_seq}")
            return False
        if seq in self._ack_seen_seqs:
            self._ack_debug(f"reject duplicate seq={seq}")
            return False
        if len(self._ack_seen_seqs) >= self._ACK_MAX_UNIQUE_TRIALS:
            self._ack_debug("reject ACK: unique-seq trial budget exhausted")
            return False
        self._ack_seen_seqs.add(seq)
        ok = decode_ack(ack_frame, self._payload, self._r2c_key, self._prk,
                        self._session_id, K=self._K)
        if not ok:
            return False
        self._ack_accepted = True
        self._ack_min_seq = seq + 1
        self._ack_debug(f"accepted seq={seq} (single-use latch set)")
        return True

    def decode_status(self) -> str:
        return self._decoder.status

    def decode_failure_reason(self) -> str | None:
        return self._decoder.failure_reason

    def decode_budget_exhausted(self) -> bool:
        return self._decoder.is_budget_exhausted

    def decode_received_symbols(self) -> int:
        return self._decoder.received_symbols

    def decode_symbol_budget(self) -> int:
        return self._decoder.max_symbols
