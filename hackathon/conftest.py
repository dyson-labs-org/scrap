import numpy as np

import sisl_crypto as sc
import sisl_framer as sf


def bits_to_hard_llrs(bits: np.ndarray, magnitude: float = 10.0) -> np.ndarray:
    """Convert a uint8 0/1 bit array to a float32 LLR array under the
    sisl_framer convention: bit 0 → +magnitude, bit 1 → -magnitude.

    Used by tests and noiseless round-trip benches that need to feed
    hard-decision encoder output through a soft-decision decoder.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    return np.where(bits == 0, magnitude, -magnitude).astype(np.float32)


def encoded_fec_bits_to_post_dbpsk(encoded_bits: np.ndarray) -> np.ndarray:
    """Convert the output of `encode_hail_fec` to the post-DBPSK basis.

    Production receiver path:
        peak_values → dbpsk_decode_from_pilot → LLRs in post-DBPSK basis
                    → decode_hail_fec_from_llrs

    The DBPSK decoder produces LLRs of the ORIGINAL FEC code bits (it
    inverts the differential encoding via the differential dot product
    z_k = Re(y_k · conj(y_{k-1}))). Tests that synthesize LLRs from a
    known bit array via `bits_to_hard_llrs` need to first transform the
    encoder output to the same post-DBPSK basis, otherwise the LLRs they
    feed into `decode_hail_fec_from_llrs` are in the wrong basis (they
    represent the channel-side differentially-encoded bits, not the
    FEC-side original bits).

    This helper inverts the differential encoding for the body region
    using the same seed convention as `encode_hail_fec`. The header
    region is uncoded and passes through unchanged.
    """
    header = encoded_bits[:sc.HAIL_FEC_HEADER_BITS]
    body_diff = encoded_bits[sc.HAIL_FEC_HEADER_BITS:]
    seed = int(header[-1])
    body_orig = sf.differential_decode_bits(body_diff, seed=seed)
    return np.concatenate([header, body_orig])


from sisl_crypto import make_test_hail_body
