"""Audio capture, WASAPI loopback enumeration, resampling, and VAD segmentation."""
from __future__ import annotations

from collections import deque
from datetime import datetime
import math
import queue
import threading
import uuid
from typing import Any, Callable, Optional

import numpy as np
import pyaudiowpatch as pyaudio
import webrtcvad

from transcribbler.config import FRAME_MS, FRAME_SAMPLES, TARGET_SR
from transcribbler.core.events import Utterance

try:
    import soxr
except ImportError:
    soxr = None
    from scipy.signal import resample_poly


class AudioResampler:
    """Exact integer decimation for 48 kHz, streaming soxr for 44.1 kHz, or buffered polyphase."""

    def __init__(self, in_rate: int, out_rate: int = TARGET_SR):
        self.in_rate = in_rate
        self.out_rate = out_rate
        self.mode = "passthrough"
        self._stream = None

        if in_rate == out_rate:
            self.mode = "passthrough"
        elif in_rate % out_rate == 0:
            self.mode = "decimate"
            self.factor = in_rate // out_rate
        elif soxr is not None:
            self.mode = "soxr"
            self._stream = soxr.ResampleStream(in_rate, out_rate, num_channels=1, quality="MQ")
        else:
            self.mode = "scipy"
            g = math.gcd(out_rate, in_rate)
            self.up, self.down = out_rate // g, in_rate // g
            self._buffer = np.zeros(0, dtype=np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.mode == "passthrough":
            return x
        if self.mode == "decimate":
            n = (len(x) // self.factor) * self.factor
            if n == 0:
                return np.zeros(0, dtype=np.int16)
            return x[:n].reshape(-1, self.factor).mean(axis=1).astype(np.int16)
        if self.mode == "soxr":
            xf = x.astype(np.float32) / 32768.0
            yf = self._stream.resample_chunk(xf)
            return np.clip(yf * 32768.0, -32768, 32767).astype(np.int16)
        # Fallback to scipy with buffering to minimize boundary artifacts
        self._buffer = np.concatenate([self._buffer, x.astype(np.float32)])
        if len(self._buffer) >= 4800:
            y = resample_poly(self._buffer, self.up, self.down)
            self._buffer = np.zeros(0, dtype=np.float32)
            return np.clip(y, -32768, 32767).astype(np.int16)
        return np.zeros(0, dtype=np.int16)


class Segmenter:
    """Splits continuous 16 kHz stream into streaming interim and final utterances using VAD and RMS."""

    def __init__(
        self,
        source: str,
        out_q: queue.Queue[Utterance],
        on_activity: Optional[Callable[[str, bool, float], None]] = None,
        on_final: Optional[Callable[[Utterance], None]] = None,
        on_interim: Optional[Callable[[Utterance], None]] = None,
        aggressiveness: int = 2,
        silence_ms: int = 450,
        soft_max_seconds: float = 5.0,
        soft_silence_ms: int = 150,
        max_seconds: float = 12.0,
        min_ms: int = 300,
        pre_speech_ms: int = 180,
        interim_interval_ms: int = 1500,
        min_interim_ms: int = 900,
    ):
        self.source = source
        self.out_q = out_q
        self.on_activity = on_activity
        self.on_final = on_final
        self.on_interim = on_interim
        self.vad = webrtcvad.Vad(aggressiveness)
        self.pending = np.zeros(0, dtype=np.int16)
        self.frames: list[np.ndarray] = []
        self.frame_rms: list[float] = []
        self.silent = 0
        self.soft_silent = 0
        self.speech_rms_ema = 0.0
        self.started: Optional[datetime] = None
        self.current_id: str = ""
        self.frames_since_interim: int = 0

        self.silence_limit = max(1, silence_ms // FRAME_MS)
        self.soft_max_frames = int(soft_max_seconds * 1000 // FRAME_MS)
        self.soft_silence_limit = max(1, soft_silence_ms // FRAME_MS)
        self.max_frames = int(max_seconds * 1000 // FRAME_MS)
        self.min_frames = max(1, min_ms // FRAME_MS)
        self.interim_interval_frames = max(1, interim_interval_ms // FRAME_MS)
        self.min_interim_frames = max(1, min_interim_ms // FRAME_MS)
        pre_frames_count = max(1, pre_speech_ms // FRAME_MS)
        self.pre_buffer: deque[np.ndarray] = deque(maxlen=pre_frames_count)

    @staticmethod
    def _calc_rms(frame: np.ndarray) -> float:
        return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) / 32768.0)

    def feed(self, pcm16: np.ndarray) -> None:
        if len(self.pending) > 0:
            self.pending = np.concatenate([self.pending, pcm16])
        else:
            self.pending = pcm16

        while len(self.pending) >= FRAME_SAMPLES:
            frame = self.pending[:FRAME_SAMPLES]
            self.pending = self.pending[FRAME_SAMPLES:]

            is_speech = self.vad.is_speech(frame.tobytes(), TARGET_SR)
            rms = self._calc_rms(frame)
            if self.on_activity:
                self.on_activity(self.source, is_speech, min(1.0, rms * 5.0))

            if is_speech:
                if not self.frames:
                    self.started = datetime.now()
                    self.current_id = uuid.uuid4().hex[:8]
                    self.frames_since_interim = 0
                    self.speech_rms_ema = rms
                    # Prepend pre-speech frames to avoid clipping initial consonants
                    for pf in self.pre_buffer:
                        self.frames.append(pf)
                        self.frame_rms.append(self._calc_rms(pf))
                self.frames.append(frame)
                self.frame_rms.append(rms)
                self.silent = 0
                self.frames_since_interim += 1

                # Detect energy-dip micro-pauses (when VAD hangover stays True during a breath pause)
                if self.speech_rms_ema > 0.0 and rms < max(0.004, self.speech_rms_ema * 0.18):
                    self.soft_silent += 1
                else:
                    self.soft_silent = 0
                    self.speech_rms_ema = 0.92 * self.speech_rms_ema + 0.08 * rms

                if (
                    len(self.frames) >= self.soft_max_frames
                    and self.soft_silent >= self.soft_silence_limit
                ):
                    self._flush()
            else:
                self.pre_buffer.append(frame)
                if self.frames:
                    self.frames.append(frame)
                    self.frame_rms.append(rms)
                    self.silent += 1
                    self.soft_silent += 1
                    self.frames_since_interim += 1
                    if self.silent >= self.silence_limit:
                        self._flush()
                    elif (
                        len(self.frames) >= self.soft_max_frames
                        and self.soft_silent >= self.soft_silence_limit
                    ):
                        self._flush()

            if self.frames:
                if len(self.frames) >= self.max_frames:
                    self._flush_at_energy_min()
                elif (
                    self.on_interim is not None
                    and self.frames_since_interim >= self.interim_interval_frames
                    and (len(self.frames) - self.silent) >= self.min_interim_frames
                ):
                    self._emit_interim()
                    self.frames_since_interim = 0

    def _emit_final_utterance(self, u: Utterance) -> None:
        if self.on_final is not None:
            self.on_final(u)
        else:
            self.out_q.put(u)

    def _emit_interim(self) -> None:
        if self.on_interim is None or self.started is None or not self.frames:
            return
        trim = max(0, self.silent - 3)
        active_frames = self.frames[:-trim] if trim > 0 else self.frames
        if not active_frames:
            return
        audio = np.concatenate(active_frames).astype(np.float32) / 32768.0
        self.on_interim(
            Utterance(
                source=self.source,
                audio=audio,
                started=self.started,
                utterance_id=self.current_id,
                is_final=False,
            )
        )

    def _flush(self) -> None:
        speech_frames_count = len(self.frames) - self.silent
        if speech_frames_count >= self.min_frames and self.started is not None:
            # Trim excess trailing silence (keep ~90ms for natural decay)
            trim = max(0, self.silent - 3)
            active_frames = self.frames[:-trim] if trim > 0 else self.frames
            if active_frames:
                audio = np.concatenate(active_frames).astype(np.float32) / 32768.0
                self._emit_final_utterance(
                    Utterance(
                        source=self.source,
                        audio=audio,
                        started=self.started,
                        utterance_id=self.current_id or uuid.uuid4().hex[:8],
                        is_final=True,
                    )
                )
        self.frames.clear()
        self.frame_rms.clear()
        self.silent = 0
        self.soft_silent = 0
        self.speech_rms_ema = 0.0
        self.started = None
        self.current_id = ""
        self.frames_since_interim = 0

    def _flush_at_energy_min(self) -> None:
        """Split continuous speech at the lowest-RMS syllable boundary and carry over trailing frames."""
        n = len(self.frames)
        if n < self.min_frames or self.started is None:
            self._flush()
            return

        # Search the last ~1.5s (up to 50 frames) for the lowest 3-frame rolling RMS energy
        search_win = min(50, max(6, n // 3))
        start_idx = max(self.min_frames, n - search_win)
        end_idx = max(start_idx + 1, n - 3)

        best_idx = end_idx
        best_energy = float("inf")
        for i in range(start_idx, end_idx + 1):
            window_energy = (
                self.frame_rms[i - 1] + self.frame_rms[i] + self.frame_rms[min(n - 1, i + 1)]
            )
            if window_energy < best_energy:
                best_energy = window_energy
                best_idx = i

        commit_frames = self.frames[: best_idx + 1]
        # Keep a 2-frame (~60ms) context overlap in the carry-over so boundary consonants aren't clipped
        carry_start = max(0, best_idx - 1)
        carry_frames = self.frames[carry_start:]
        carry_rms = self.frame_rms[carry_start:]

        if commit_frames:
            audio = np.concatenate(commit_frames).astype(np.float32) / 32768.0
            self._emit_final_utterance(
                Utterance(
                    source=self.source,
                    audio=audio,
                    started=self.started,
                    utterance_id=self.current_id or uuid.uuid4().hex[:8],
                    is_final=True,
                )
            )

        self.frames = list(carry_frames)
        self.frame_rms = list(carry_rms)
        self.silent = 0
        self.soft_silent = 0
        self.started = datetime.now()
        self.current_id = uuid.uuid4().hex[:8]
        self.frames_since_interim = 0

    def reset(self) -> None:
        """Clear all buffered frames and reset state (used when muted/disabled)."""
        self.frames.clear()
        self.frame_rms.clear()
        self.pending = np.zeros(0, dtype=np.int16)
        self.silent = 0
        self.soft_silent = 0
        self.speech_rms_ema = 0.0
        self.started = None
        self.current_id = ""
        self.frames_since_interim = 0


def get_audio_devices(p: pyaudio.PyAudio) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (input_mics, loopback_speakers)."""
    mics = []
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev.get("maxInputChannels", 0) > 0 and not dev.get("isLoopbackDevice", False):
            mics.append(dev)

    speakers = list(p.get_loopback_device_info_generator())
    return mics, speakers


def list_devices(p: pyaudio.PyAudio) -> None:
    """Print available input and loopback devices to stdout."""
    print("\n--- Available Input Devices ---")
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev.get("maxInputChannels", 0) > 0 and not dev.get("isLoopbackDevice", False):
            print(f"  [{i}] {dev['name']} (Rate: {int(dev['defaultSampleRate'])} Hz, "
                  f"Channels: {dev['maxInputChannels']})")

    print("\n--- Available WASAPI Loopback Devices (Speakers / System) ---")
    for dev in p.get_loopback_device_info_generator():
        print(f"  [{dev['index']}] {dev['name']} (Rate: {int(dev['defaultSampleRate'])} Hz, "
              f"Channels: {dev['maxInputChannels']})")
    print()


def find_loopback(p: pyaudio.PyAudio, device_index: Optional[int] = None) -> dict[str, Any]:
    """Find the best WASAPI loopback device, or use the given index."""
    if device_index is not None:
        return p.get_device_info_by_index(device_index)

    # 1. Try PyAudioWPatch default WASAPI loopback helper
    if hasattr(p, "get_default_wasapi_loopback"):
        try:
            return p.get_default_wasapi_loopback()
        except OSError:
            pass

    # 2. Fallback to searching WASAPI output speakers loopback
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    speakers = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if speakers.get("isLoopbackDevice"):
        return speakers

    for dev in p.get_loopback_device_info_generator():
        if speakers["name"] in dev["name"]:
            return dev

    # 3. Fallback to first available loopback device
    for dev in p.get_loopback_device_info_generator():
        return dev

    raise RuntimeError("No WASAPI loopback device found. Ensure default speakers are connected.")


class Capture:
    """Captures from an audio endpoint, downsamples to 16 kHz mono, and feeds Segmenter."""

    def __init__(self, p: pyaudio.PyAudio, dev: dict[str, Any], segmenter: Segmenter):
        self.ch = int(dev["maxInputChannels"])
        self.sr = int(dev["defaultSampleRate"])
        self.segmenter = segmenter
        self.resampler = AudioResampler(self.sr, TARGET_SR)
        self.raw_queue: queue.Queue[Optional[bytes]] = queue.Queue()
        self.running = threading.Event()
        self.running.set()
        self.enabled = threading.Event()
        self.enabled.set()

        self.stream = p.open(
            format=pyaudio.paInt16,
            channels=self.ch,
            rate=self.sr,
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=1024,
            stream_callback=self._callback,
        )
        self.thread = threading.Thread(target=self._process, daemon=True)
        self.thread.start()

    def set_enabled(self, enabled: bool) -> None:
        """Dynamically enable or disable capture for this channel."""
        if enabled:
            self.enabled.set()
        else:
            self.enabled.clear()
            self.segmenter.reset()

    def _callback(self, in_data, frame_count, time_info, status):
        if self.running.is_set() and self.enabled.is_set():
            self.raw_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def _process(self) -> None:
        while self.running.is_set():
            try:
                data = self.raw_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if data is None:
                break

            # Convert multi-channel int16 to mono
            x = np.frombuffer(data, dtype=np.int16)
            if self.ch > 1:
                x = x.reshape(-1, self.ch).mean(axis=1).astype(np.int16)

            # Resample and feed to VAD segmenter
            y = self.resampler.process(x)
            if len(y) > 0:
                self.segmenter.feed(y)

    def close(self) -> None:
        self.running.clear()
        self.raw_queue.put(None)
        try:
            self.stream.stop_stream()
            self.stream.close()
        except Exception:
            pass
