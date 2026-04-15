from __future__ import annotations

from sparse_rlnc import RLNCEncoder, RLNCDecoder
from sisl_payload import encode_payload_symbol, decode_payload_symbol, encode_ack, decode_ack
from sisl_crypto import derive_session_prk


class RLNCSession:
    def __init__(self, payload: bytes, K: int, session_keys: dict):
        self._payload = payload
        self._K = K
        self._session_keys = session_keys
        self._prk = derive_session_prk(session_keys)
        self._session_id = session_keys["session_id"]
        self._tx_key = session_keys["p2p_tx_key"]
        self._rx_key = session_keys["p2p_rx_key"]
        self._encoder = RLNCEncoder(payload, K, self._prk)
        self._decoder = RLNCDecoder(K, self._prk)
        self._next_comb_id = 0
        self._recovered: bytes | None = None

    def next_tx_frame(self) -> bytes:
        comb_id = self._next_comb_id
        self._next_comb_id += 1
        _, encoded_bytes, _ = self._encoder.encode_symbol(comb_id)
        return encode_payload_symbol(comb_id, encoded_bytes, self._tx_key, self._prk, self._session_id)

    def rx_frame(self, frame: bytes) -> bool:
        comb_id, plain = decode_payload_symbol(frame, self._tx_key, self._prk, self._session_id)
        complete = self._decoder.add_symbol(comb_id, plain)
        if complete and self._recovered is None:
            raw = self._decoder.decode()
            self._recovered = raw[: len(self._payload)] if raw is not None else None
        return complete

    def recovered_payload(self) -> bytes | None:
        return self._recovered

    def build_ack(self) -> bytes | None:
        if self._recovered is None:
            return None
        return encode_ack(self._payload, self._rx_key, self._prk, self._session_id)

    def verify_ack(self, ack_frame: bytes) -> bool:
        return decode_ack(ack_frame, self._payload, self._rx_key, self._prk, self._session_id)
