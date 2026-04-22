from __future__ import annotations

import collections
import platform
import queue as _queue
import sys
import time
from typing import Any

import numpy as np

import sisl_framer as sf
from sdr_devices import DEVICES, get_device_ppm as _get_device_ppm

CENTER_FREQ_HZ = 2_437_000_000
CHIP_RATE_HZ = 1_000_000
SAMP_RATE_HZ = 8_000_000
SAMPS_PER_CHIP = SAMP_RATE_HZ // CHIP_RATE_HZ
HACKRF_TX_VGA_DB = 0
HACKRF_TX_AMP_ON = False

_IS_WINDOWS = platform.system() == "Windows"


def _is_debug_output_enabled() -> bool:
    return bool(getattr(sf, "SISL_DEBUG", False))


def upsample_chips_to_samples(chips: np.ndarray,
                              samps_per_chip: float = SAMPS_PER_CHIP
                              ) -> np.ndarray:
    """Zero-order-hold upsample chips to complex baseband samples."""
    n = int(round(samps_per_chip))
    rep = np.repeat(chips.astype(np.float32), n)
    return rep.astype(np.complex64)


def _open_soapy_with_retry(device_str: str, attempts: int = 10):
    """Open a SoapySDR device with up to *attempts* retries (3 s apart)."""
    import SoapySDR as _SoapySDR
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return _SoapySDR.Device(device_str)
        except RuntimeError as exc:
            last_exc = exc
            if attempt == attempts - 1:
                raise
            time.sleep(3.0)
    raise RuntimeError("unreachable") from last_exc


def _read_device_serial(device, SoapySDR, device_str: str) -> str:
    """Read serial from an already-opened SoapySDR device."""
    serial = ""
    try:
        hw_dict = dict(device.getHardwareInfo())
        serial = hw_dict.get("serial", "")
    except Exception:
        pass
    if not serial:
        try:
            found = SoapySDR.Device.enumerate(device_str)
            if found:
                serial = str(dict(found[0]).get("serial", ""))
        except Exception:
            pass
    return serial


class SoapyDevice:
    """Context manager for a persistent SoapySDR device handle."""

    def __init__(
        self,
        device_name: str = "hackrf",
        center_hz: float = CENTER_FREQ_HZ,
        device_str: str | None = None,
        open_attempts: int = 10,
    ) -> None:
        import SoapySDR as _SoapySDR
        self._SoapySDR = _SoapySDR
        if device_name not in DEVICES:
            raise ValueError(
                f"unknown device {device_name!r}; choices: {list(DEVICES.keys())}")
        self.device_name = device_name
        info = DEVICES[device_name]
        if device_str is None:
            device_str = info.driver
        self._device_str = device_str
        self._info = info

        self.device: Any = _open_soapy_with_retry(device_str, attempts=open_attempts)

        serial = self._read_serial()
        self.serial = serial
        cal_ppm = _get_device_ppm(serial)
        self._cal_ppm = cal_ppm
        if cal_ppm != 0.0:
            ppm_offset_hz = center_hz * cal_ppm / 1e6
            center_hz += ppm_offset_hz
            if _is_debug_output_enabled():
                short_serial = serial.lstrip("0") or serial
                print(f"  PPM cal: device {short_serial} → {cal_ppm:+.1f} ppm "
                      f"({ppm_offset_hz:+.0f} Hz)")
        self.center_hz: float = center_hz

    def _read_serial(self) -> str:
        return _read_device_serial(self.device, self._SoapySDR, self._device_str)

    def close(self) -> None:
        dev = self.device
        if dev is not None:
            self.device = None  # type: ignore[assignment]
            try:
                dev.close()
            except Exception:
                pass

    def reopen(self) -> None:
        """Close and reopen the device handle."""
        self.close()
        time.sleep(0.3)
        for attempt in range(10):
            try:
                self.device = self._SoapySDR.Device(self._device_str)
                return
            except RuntimeError:
                if attempt == 9:
                    raise
                time.sleep(3.0)

    def __enter__(self) -> "SoapyDevice":
        return self

    def __exit__(self, *_) -> None:
        self.close()


def soapy_tx_burst(
    samples: np.ndarray,
    center_hz: float,
    samp_hz: float = SAMP_RATE_HZ,
    tx_vga_db: int = HACKRF_TX_VGA_DB,
    tx_amp_on: bool = HACKRF_TX_AMP_ON,
    repeats: int = 1,
    device_str: str = "driver=hackrf",
    device=None,
) -> None:
    """Transmit a finite sample buffer via SoapySDR (no GnuRadio)."""
    import SoapySDR
    from SoapySDR import SOAPY_SDR_TX, SOAPY_SDR_CF32

    _owns_device = device is None
    if _owns_device:
        device = _open_soapy_with_retry(device_str)
    assert device is not None
    device.setSampleRate(SOAPY_SDR_TX, 0, samp_hz)
    device.setFrequency(SOAPY_SDR_TX, 0, center_hz)
    device.setGain(SOAPY_SDR_TX, 0, "VGA", float(tx_vga_db))
    device.setGain(SOAPY_SDR_TX, 0, "AMP", 14.0 if tx_amp_on else 0.0)

    import time as _time_tx2
    t_setup = _time_tx2.time()
    stream = device.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32)
    if sf.SISL_DEBUG:
        sf.debug_telemetry(
            "tx",
            stream=sys.stderr,
            status="setup_stream",
            elapsed_s=_time_tx2.time() - t_setup,
        )
    t_act = _time_tx2.time()
    device.activateStream(stream)
    if sf.SISL_DEBUG:
        sf.debug_telemetry(
            "tx",
            stream=sys.stderr,
            status="activate_stream",
            elapsed_s=_time_tx2.time() - t_act,
        )

    full = np.tile(samples, repeats) if repeats > 1 else samples
    offset = 0
    chunk = 65536
    last_end = len(full)
    t_write = _time_tx2.time()
    _chk = last_end // 6
    while offset < last_end:
        end = min(offset + chunk, last_end)
        is_last = (end == last_end)
        flags = SoapySDR.SOAPY_SDR_END_BURST if is_last else 0
        sr = device.writeStream(stream, [full[offset:end]], end - offset,
                                flags, timeoutUs=1_000_000)
        if sr.ret > 0:
            offset += sr.ret
            if sf.SISL_DEBUG and offset >= _chk:
                sf.debug_telemetry(
                    "tx",
                    stream=sys.stderr,
                    status="write_progress",
                    samples_written=offset,
                    elapsed_s=_time_tx2.time() - t_write,
                )
                _chk += last_end // 6
        elif sr.ret == SoapySDR.SOAPY_SDR_TIMEOUT:
            continue
        else:
            print(f'  [TX ERROR] writeStream ret={sr.ret}', file=sys.stderr)
            break
    if sf.SISL_DEBUG:
        sf.debug_telemetry(
            "tx",
            stream=sys.stderr,
            status="write_done",
            elapsed_s=_time_tx2.time() - t_write,
        )

    _time_tx2.sleep(0.3)
    t_deact = _time_tx2.time()
    try:
        device.deactivateStream(stream)
    except Exception:
        pass
    if sf.SISL_DEBUG:
        sf.debug_telemetry(
            "tx",
            stream=sys.stderr,
            status="deactivate_stream",
            elapsed_s=_time_tx2.time() - t_deact,
        )
    t_cs = _time_tx2.time()
    try:
        device.closeStream(stream)
    except Exception:
        pass
    if sf.SISL_DEBUG:
        sf.debug_telemetry(
            "tx",
            stream=sys.stderr,
            status="close_stream",
            elapsed_s=_time_tx2.time() - t_cs,
        )
    if _owns_device:
        device.close()


def soapy_tx_streaming(
    symbol_iter,
    center_hz: float,
    samp_hz: float = SAMP_RATE_HZ,
    tx_vga_db: int = HACKRF_TX_VGA_DB,
    tx_amp_on: bool = HACKRF_TX_AMP_ON,
    device=None,
) -> int:
    """Stream-encode TX symbols one at a time."""
    import SoapySDR
    from SoapySDR import SOAPY_SDR_TX, SOAPY_SDR_CF32
    import time as _t

    assert device is not None
    device.setSampleRate(SOAPY_SDR_TX, 0, samp_hz)
    device.setFrequency(SOAPY_SDR_TX, 0, center_hz)
    device.setGain(SOAPY_SDR_TX, 0, "VGA", float(tx_vga_db))
    device.setGain(SOAPY_SDR_TX, 0, "AMP", 14.0 if tx_amp_on else 0.0)

    stream = device.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32)
    device.activateStream(stream)

    chunk = 65536
    n_sent = 0
    try:
        for samples in symbol_iter:
            offset = 0
            last_end = len(samples)
            while offset < last_end:
                end = min(offset + chunk, last_end)
                sr = device.writeStream(
                    stream, [samples[offset:end]], end - offset,
                    0, timeoutUs=1_000_000,
                )
                if sr.ret > 0:
                    offset += sr.ret
                elif sr.ret == SoapySDR.SOAPY_SDR_TIMEOUT:
                    continue
                else:
                    print(f'  [TX ERROR] writeStream ret={sr.ret}', file=sys.stderr)
                    break
            n_sent += 1
    finally:
        _t.sleep(0.3)
        try:
            device.deactivateStream(stream)
        except Exception:
            pass
        try:
            device.closeStream(stream)
        except Exception:
            pass

    return n_sent


def _usb_reader_thread(
    device,
    stream,
    block_samples: int,
    block_queue: _queue.Queue,
    stop_event,
    stats: dict,
) -> None:
    """Background thread: drain SDR USB buffer into a queue of numpy blocks."""
    read_chunk = 32768 if _IS_WINDOWS else 0

    local_buf = np.empty(block_samples, dtype=np.complex64)
    while not stop_event.is_set():
        filled = 0
        fatal_error = False
        while filled < block_samples and not stop_event.is_set():
            remain = block_samples - filled
            want = min(read_chunk, remain) if read_chunk else remain
            sr = device.readStream(
                stream, [local_buf[filled:filled + want]],
                want, timeoutUs=50_000,
            )
            if sr.ret > 0:
                filled += sr.ret
            elif sr.ret == -1:
                continue
            elif sr.ret == -4:
                stats["overflows"] += 1
                continue
            else:
                fatal_error = True
                break
        if fatal_error:
            block_queue.put(None)
            return
        if filled >= block_samples // 2 and not stop_event.is_set():
            blk = local_buf[:filled].copy()
            while True:
                try:
                    block_queue.put_nowait(blk)
                    break
                except _queue.Full:
                    try:
                        block_queue.get_nowait()
                        stats["dropped_blocks"] += 1
                    except _queue.Empty:
                        break
            local_buf = np.empty(block_samples, dtype=np.complex64)
    block_queue.put(None)


class _AgcPpmState:
    """Encapsulates AGC and PPM calibration state for live RX."""

    RECAL_INTERVAL = 10.0
    SETTLED_THRESHOLD_HZ = 500.0
    AGC_TARGET = 200.0
    AGC_MIN_PEAK = 50.0
    AGC_MAX_PEAK = 400.0

    def __init__(self, device_name: str, device, center_hz: float,
                 vga_db: float, lna_db: float,
                 initial_vga_db: float | None = None,
                 disable_auto_ppm: bool = False):
        self._device_name = device_name
        self._device = device
        self._center_hz = float(center_hz)
        self._nominal_center_hz = float(center_hz)
        self._total_correction_hz = 0.0
        self._last_recal_t = time.time()
        self._offset_history: collections.deque[float] = collections.deque(maxlen=8)
        self._disable_auto_ppm = disable_auto_ppm

        if device_name == "hackrf":
            self._vga_min, self._vga_max = 0.0, 62.0
        else:
            self._vga_min, self._vga_max = 0.0, 49.0

        if initial_vga_db is not None:
            self._current_vga = float(initial_vga_db)
            self._agc_warmup_blocks = 0
            self._blocks_seen = 0
            self._agc_stable = True
            self._settled = True
            self._clip_count = 0
            self._disable_clip_agc = True
            self._freeze_vga = True
        else:
            if device_name == "hackrf":
                self._current_vga = float(vga_db)
            else:
                self._current_vga = max(0.0, min(49.0, float(lna_db + vga_db)))
            self._agc_warmup_blocks = 3
            self._blocks_seen = 0
            self._agc_stable = False
            self._settled = False
            self._clip_count = 0
            self._disable_clip_agc = False
            self._freeze_vga = False

        self._prev_vga = self._current_vga
        self._vga_ceiling = self._vga_max

    @property
    def final_vga_db(self) -> float:
        return self._current_vga

    @property
    def final_center_hz(self) -> float:
        return self._center_hz

    def _set_rx_vga(self, gain: float) -> None:
        from SoapySDR import SOAPY_SDR_RX
        if self._device_name == "hackrf":
            self._device.setGain(SOAPY_SDR_RX, 0, "VGA", gain)
        else:
            self._device.setGain(SOAPY_SDR_RX, 0, gain)

    def on_block(self, result: dict) -> None:
        self._blocks_seen += 1
        self._update_agc(result)
        if self._disable_auto_ppm:
            return
        gain_changed = (self._current_vga != self._prev_vga)
        self._prev_vga = self._current_vga
        if not self._agc_stable:
            if self._blocks_seen >= self._agc_warmup_blocks and not gain_changed:
                self._agc_stable = True
                if _is_debug_output_enabled():
                    print("       AGC stable — static PPM cal (no auto-PPM)")
        if self._agc_stable:
            self._update_ppm(result)

    def _update_ppm(self, result: dict) -> None:
        from SoapySDR import SOAPY_SDR_RX
        s = result.get("status", "")
        if s in ("no_signal", "short_block"):
            return
        foff = result.get("freq_offset_hz")
        now = time.time()
        MAX_FOFF_HZ = max(100_000.0, self._nominal_center_hz * 40e-6)
        if foff is not None and abs(foff) > 0 and abs(foff) <= MAX_FOFF_HZ:
            self._offset_history.append(foff)
            do_retune = False
            if not self._settled:
                do_retune = len(self._offset_history) >= 2
            elif now - self._last_recal_t >= self.RECAL_INTERVAL:
                do_retune = True
            if do_retune and self._offset_history:
                correction = float(np.median(list(self._offset_history)[-4:]))
                self._center_hz += correction
                self._total_correction_hz += correction
                self._device.setFrequency(
                    SOAPY_SDR_RX, 0, self._center_hz)
                total_ppm = (self._total_correction_hz
                             / self._nominal_center_hz * 1e6)
                if _is_debug_output_enabled():
                    print(f"       AUTO-PPM: retune {correction:+.0f} Hz "
                          f"(total {self._total_correction_hz:+.0f} Hz / "
                          f"{total_ppm:+.1f} ppm)")
                self._offset_history.clear()
                self._last_recal_t = now
                if abs(correction) < self.SETTLED_THRESHOLD_HZ:
                    self._settled = True

    def _update_agc(self, result: dict) -> None:
        if self._freeze_vga:
            return
        sample_p99 = float(result.get("sample_p99", 0.0))
        if (not self._disable_clip_agc
                and sample_p99 > 0.9 and self._current_vga > self._vga_min):
            self._clip_count += 1
            if self._clip_count >= 2:
                reduce_db = min(6.0, max(3.0,
                                20.0 * np.log10(sample_p99 / 0.5)))
                self._current_vga = max(
                    self._vga_min, self._current_vga - reduce_db)
                self._vga_ceiling = self._current_vga
                self._set_rx_vga(self._current_vga)
                print(f"       AGC: sustained clipping (p99={sample_p99:.2f}), "
                      f"gain → {self._current_vga:.0f} dB "
                      f"(ceiling set)")
            else:
                print(f"       AGC: transient clipping (p99={sample_p99:.2f}), "
                      f"monitoring")
        else:
            self._clip_count = 0
            pk = result.get("peak_mag")
            periodic_ratio = result.get("periodic_ratio", 0.0)
            if pk is not None and pk > 1 and periodic_ratio >= 0.3:
                if pk < self.AGC_MIN_PEAK or pk > self.AGC_MAX_PEAK:
                    step_db = 10.0 * np.log10(self.AGC_TARGET / pk)
                    step_db = max(-6.0, min(6.0, step_db))
                    new_vga = max(self._vga_min, min(
                        self._vga_ceiling, self._current_vga + step_db))
                    if abs(new_vga - self._current_vga) >= 1.0:
                        self._current_vga = round(new_vga)
                        self._set_rx_vga(self._current_vga)
                        print(f"       AGC: peak={pk:.0f} (periodic_ratio={periodic_ratio:.2f}), "
                              f"gain → {self._current_vga:.0f} dB")
