"""Shared typed contracts for SISL cross-module decode boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NotRequired, TypeAlias, TypedDict

import numpy as np

if TYPE_CHECKING:
    import sisl_crypto as sc


SoftAsmCandidate: TypeAlias = tuple[int, float, float]


@dataclass(frozen=True)
class CandidateWindow:
    """Metadata for one candidate decode window."""

    bit_offset: int
    frame_bits: int
    soft_score: float
    pts_ratio: float


class LlrExtractionResult(TypedDict):
    fec_llrs: np.ndarray | None
    phase_rms_residual_rad: float | None
    asm_errs_in_coherent: int | None


class AccumulatorInput(TypedDict, total=False):
    fec_llrs: np.ndarray
    freq_offset_hz: float | None


class AcquireTrackOk(TypedDict):
    status: Literal["acquired"]
    peak_values: list
    positions: list[int]
    freq_hz: float
    peak_mag: float
    median_mag: float
    rad_per_sample: float


class AcquireTrackFailure(TypedDict, total=False):
    status: Literal["short_block", "no_signal", "acquire_failed"]
    peak_mag: float
    median_mag: float
    rad_per_sample: float
    freq_offset_hz: float
    periodic_ratio: float
    note: str


AcquireTrackResult: TypeAlias = AcquireTrackOk | AcquireTrackFailure


class DecodeResultBase(TypedDict, total=False):
    status: Literal["decrypt_ok", "decrypt_fail", "track_lost"]
    start_sample: int
    asm_at_byte: str
    peak_mag: float
    median_mag: float
    rad_per_sample: float
    freq_offset_hz: float
    soft_score: float
    pts_ratio: float
    polarity: str
    note: str
    fec_llrs: np.ndarray
    extra_fec_llrs: list[np.ndarray]
    phase_rms_residual_rad: float | None
    asm_errs_in_coherent: int | None
    _freq_rad: float
    _multi_results: list["FrameDecodeResult"]


class HailDecryptOk(DecodeResultBase):
    status: Literal["decrypt_ok"]
    body: "sc.HailBody"
    caller_eph_pub_canonical: bytes
    decoded_hail: "sc.DecodedHail"


class AckDecryptOk(DecodeResultBase):
    status: Literal["decrypt_ok"]
    body: "sc.AckBody"
    decoded_ack: "sc.DecodedAck"


class DecryptFail(DecodeResultBase):
    status: Literal["decrypt_fail"]
    polarity: str


class TrackLost(DecodeResultBase):
    status: Literal["track_lost"]
    note: NotRequired[str]


FrameDecodeResult: TypeAlias = HailDecryptOk | AckDecryptOk | DecryptFail | TrackLost


class PayloadDecodeResult(TypedDict, total=False):
    status: Literal["decrypt_ok", "decrypt_fail"]
    payload_frame_bytes: bytes
    asm_at_byte: str
    soft_score: float
    peak_mag: float
    median_mag: float
    rad_per_sample: float
    freq_offset_hz: float
    start_sample: int
    note: str


class SessionKeys(TypedDict):
    p2p_tx_key: bytes
    p2p_rx_key: bytes
    spreading_seed: bytes
    session_id: bytes
    reserved: bytes
