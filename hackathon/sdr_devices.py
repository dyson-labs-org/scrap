"""Shared SDR device configuration for HackRF and RTL-SDR.

Centralizes DeviceInfo, device registry, plugin install hints,
and diagnostic helpers used by sisl_dsss_demo, rf_power, and
bench_radio_characterize.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass
class DeviceInfo:
    name: str
    driver: str
    samp_hz: int
    samps_per_chip: int
    freq_min_hz: int
    freq_max_hz: int
    notes: str
    gain_stages: tuple[str, ...] = ()


# Per-device PPM calibration, keyed by serial number. Measured relative
# to HackRF #0 (930c64dc279e7bc3) as the TX reference. The PPM offset
# is a property of each device's crystal oscillator and is constant
# across frequencies. Applied automatically when the device is opened.
#
# To recalibrate: TX at 915 MHz with the reference HackRF, RX with the
# target device, read the converged Δf from the first DECRYPTED block:
#   ppm = Δf_hz / 915e6 * 1e6
DEVICE_PPM: dict[str, float] = {
    "930c64dc279e7bc3": +16.2,    # HackRF #0 — measured: uncal Δf=+39.6kHz, need +16.2ppm to null
    "78d063dc2b6d2267": -19.1,    # HackRF #1
    "930c64dc29144ac3": +16.6,    # HackRF #2
    "00000001":         -22.2,    # Nooelec SMArt XTR v5 (RTL-SDR)
}


# Minimum tx-vga (and whether --tx-amp is required) per nominal band center,
# measured OTA with HackRF loopback at ~1 m using the full RLNC call/respond
# sequence (hail + payload TX + ACK).  These are floor values for the test
# bench; real deployments should add headroom.  Lookup uses nearest frequency.
#
# Measured 2026-04-20 with HackRF pair 930c64dc279e7bc3 / 78d063dc2b6d2267,
# stock antennas, binary search over 0–47 dB, 290 s timeout per test.
BAND_MIN_VGA: dict[int, tuple[int, bool]] = {
    433_000_000:    (24, False),
    915_000_000:    ( 3, False),
    2_437_000_000:  (21, False),
    5_825_000_000:  (47, True),   # also requires --tx-amp
}


def get_band_min_vga(freq_hz: float) -> tuple[int, bool]:
    """Return (min_vga_db, tx_amp_required) for the nearest calibrated band."""
    nearest = min(BAND_MIN_VGA, key=lambda f: abs(f - freq_hz))
    return BAND_MIN_VGA[nearest]


def get_device_ppm(serial: str) -> float:
    """Look up the calibrated PPM for a device by serial number.

    Strips leading zeros from the serial so both the full 32-char
    SoapySDR format (0000000000000000930c64dc29144ac3) and the short
    16-char format (930c64dc29144ac3) match the same entry.
    """
    serial = serial.lstrip("0") or "0"
    for key, ppm in DEVICE_PPM.items():
        if key.lstrip("0") == serial:
            return ppm
    return 0.0


DEVICES: dict[str, DeviceInfo] = {
    "hackrf": DeviceInfo(
        name="HackRF One",
        driver="driver=hackrf",
        samp_hz=8_000_000,
        samps_per_chip=8,
        freq_min_hz=1_000_000,
        freq_max_hz=6_000_000_000,
        notes="TX + RX, 1 MHz – 6 GHz, 8-bit ADC, 3 gain stages",
        gain_stages=("AMP", "LNA", "VGA"),
    ),
    "rtlsdr": DeviceInfo(
        name="NESDR / RTL-SDR",
        driver="driver=rtlsdr",
        samp_hz=2_000_000,
        samps_per_chip=2,
        freq_min_hz=24_000_000,
        freq_max_hz=1_766_000_000,
        notes="RX only, 24–1766 MHz, 8-bit ADC, single tuner gain",
        gain_stages=("TUNER",),
    ),
}


PLUGIN_INSTALL_HINTS: dict[str, str] = {
    "hackrf": (
        "  Arch:   sudo pacman -S soapyhackrf\n"
        "  Debian: sudo apt install soapysdr-module-hackrf\n"
        "  From source: https://github.com/pothosware/SoapyHackRF"
    ),
    "rtlsdr": (
        "  Arch:   sudo pacman -S soapyrtlsdr\n"
        "  Debian: sudo apt install soapysdr-module-rtlsdr\n"
        "  From source: https://github.com/pothosware/SoapyRTLSDR"
    ),
}


def format_device_open_error(soapy_module, info: DeviceInfo,
                             err: Exception) -> str:
    """Produce a human-readable explanation for SoapySDR device-open failures."""
    try:
        enumerated = soapy_module.Device.enumerate()
    except Exception:
        enumerated = []

    found_drivers = []
    for d in enumerated:
        try:
            drv = d.get("driver", "?") if hasattr(d, "get") else "?"
        except Exception:
            drv = "?"
        found_drivers.append(str(drv))

    lines = [
        f"failed to open {info.name} with '{info.driver}': {err}",
        "",
        "SoapySDR enumerated the following devices:",
    ]
    if enumerated:
        for i, d in enumerate(enumerated):
            try:
                lines.append(f"  [{i}] {dict(d)}")
            except Exception:
                lines.append(f"  [{i}] {d}")
    else:
        lines.append("  (none — no SoapySDR plugins found matching any device)")

    driver_key = info.driver.replace("driver=", "")
    if driver_key not in found_drivers:
        lines.append("")
        lines.append(
            f"The '{driver_key}' driver is NOT among SoapySDR's loaded plugins."
        )
        lines.append(
            f"Install the Soapy{driver_key.upper()} plugin and retry:"
        )
        hint = PLUGIN_INSTALL_HINTS.get(driver_key,
                                        f"  (no install hint for {driver_key})")
        lines.append(hint)
        lines.append("")
        lines.append("After installing, verify with:  SoapySDRUtil --find")

    return "\n".join(lines)


