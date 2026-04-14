import pytest

from sisl_crypto import derive_session_keys, derive_session_prk
from sisl_payload import decode_ack, decode_payload_symbol, encode_ack, encode_payload_symbol

_CALLER_PRIV_BYTES = bytes(range(32))
_RESP_PRIV_BYTES = bytes(range(1, 33))


def _make_session_keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from sisl_crypto import CURVE, ecdh, pubkey_to_compressed
    caller_priv = ec.derive_private_key(int.from_bytes(_CALLER_PRIV_BYTES, 'big'), CURVE)
    resp_priv = ec.derive_private_key(int.from_bytes(_RESP_PRIV_BYTES, 'big'), CURVE)
    caller_pub = caller_priv.public_key()
    resp_pub = resp_priv.public_key()
    dh1 = ecdh(caller_priv, resp_pub)
    dh2 = ecdh(resp_priv, caller_pub)
    dh3 = dh1
    caller_eph = pubkey_to_compressed(caller_pub)
    resp_eph = pubkey_to_compressed(resp_pub)
    return derive_session_keys(dh1, dh2, dh3, caller_eph, resp_eph)


@pytest.fixture(scope="module")
def session():
    keys = _make_session_keys()
    prk = derive_session_prk(keys)
    return keys, prk


def test_payload_roundtrip(session):
    keys, prk = session
    comb_id = 42
    data = b"hello encoded symbol"
    frame = encode_payload_symbol(comb_id, data, keys["p2p_tx_key"], prk, keys["session_id"])
    got_id, got_data = decode_payload_symbol(frame, keys["p2p_tx_key"], prk, keys["session_id"])
    assert got_id == comb_id
    assert got_data == data


def test_payload_wrong_key(session):
    keys, prk = session
    frame = encode_payload_symbol(7, b"data", keys["p2p_tx_key"], prk, keys["session_id"])
    with pytest.raises(ValueError):
        decode_payload_symbol(frame, keys["p2p_rx_key"], prk, keys["session_id"])


def test_payload_tampered_ciphertext(session):
    keys, prk = session
    frame = bytearray(encode_payload_symbol(3, b"data", keys["p2p_tx_key"], prk, keys["session_id"]))
    frame[5] ^= 0xFF
    with pytest.raises(ValueError):
        decode_payload_symbol(bytes(frame), keys["p2p_tx_key"], prk, keys["session_id"])


def test_payload_tampered_comb_id(session):
    keys, prk = session
    frame = bytearray(encode_payload_symbol(3, b"data", keys["p2p_tx_key"], prk, keys["session_id"]))
    frame[1] ^= 0xFF
    with pytest.raises(ValueError):
        decode_payload_symbol(bytes(frame), keys["p2p_tx_key"], prk, keys["session_id"])


def test_ack_roundtrip(session):
    keys, prk = session
    payload = b"original payload bytes"
    frame = encode_ack(payload, keys["p2p_rx_key"], prk, keys["session_id"])
    assert decode_ack(frame, payload, keys["p2p_rx_key"], prk, keys["session_id"])


def test_ack_wrong_payload(session):
    keys, prk = session
    frame = encode_ack(b"correct payload", keys["p2p_rx_key"], prk, keys["session_id"])
    assert not decode_ack(frame, b"wrong payload", keys["p2p_rx_key"], prk, keys["session_id"])


def test_ack_tampered(session):
    keys, prk = session
    frame = bytearray(encode_ack(b"payload", keys["p2p_rx_key"], prk, keys["session_id"]))
    frame[0] ^= 0xFF
    result = decode_ack(bytes(frame), b"payload", keys["p2p_rx_key"], prk, keys["session_id"])
    assert not result


def test_payload_iv_uniqueness(session):
    keys, prk = session
    data = b"same plaintext"
    frame0 = encode_payload_symbol(0, data, keys["p2p_tx_key"], prk, keys["session_id"])
    frame1 = encode_payload_symbol(1, data, keys["p2p_tx_key"], prk, keys["session_id"])
    assert frame0[4:] != frame1[4:]


def test_frame_sizes(session):
    keys, prk = session
    data = b"twelve bytes"
    frame = encode_payload_symbol(0, data, keys["p2p_tx_key"], prk, keys["session_id"])
    assert len(frame) == 4 + len(data) + 16
    ack = encode_ack(b"payload", keys["p2p_rx_key"], prk, keys["session_id"])
    assert len(ack) == 48
