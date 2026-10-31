"""Audio capture, WASAPI loopback enumeration, resampling, and VAD segmentation."""
from __future__ import annotations

from collections import deque
from datetime import datetime
import math
import queue
import threading
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
    """Splits continuous 16 kHz stream into utterances using WebRTC VAD and pre-speech buffer."""

    def __init__(
        self,
        source: str,
        out_q: queue.Queue[Utterance],
        on_activity: Optional[Callable[[str, bool, float], None]] = None,
        aggressiveness: int = 2,
        silence_ms: int = 700,
        max_seconds: int = 25,
        min_ms: int = 300,
        pre_speech_ms: int = 180,
    ):
        self.source = source
        self.out_q = out_q
        self.on_activity = on_activity
        self.vad = webrtcvad.Vad(aggressiveness)
        self.pending = np.zeros(0, dtype=np.int16)
        self.frames: list[np.ndarray] = []
        self.silent = 0
        self.started: Optional[datetime] = None

        self.silence_limit = silence_ms // FRAME_MS
        self.max_frames = max_seconds * 1000 // FRAME_MS
        self.min_frames = min_ms // FRAME_MS
        pre_frames_count = max(1, pre_speech_ms // FRAME_MS)
        self.pre_buffer: deque[np.ndarray] = deque(maxlen=pre_frames_count)

    def feed(self, pcm16: np.ndarray) -> None:
        if len(self.pending) > 0:
            self.pending = np.concatenate([self.pending, pcm16])
        else:
            self.pending = pcm16

        while len(self.pending) >= FRAME_SAMPLES:
            frame = self.pending[:FRAME_SAMPLES]
            self.pending = self.pending[FRAME_SAMPLES:]

            is_speech = self.vad.is_speech(frame.tobytes(), TARGET_SR)
            if self.on_activity:
                # Compute RMS energy normalized roughly between 0.0 and 1.0
                rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) / 32768.0)
                self.on_activity(self.source, is_speech, min(1.0, rms * 5.0))

            if is_speech:
                if not self.frames:
                    self.started = datetime.now()
                    # Prepend pre-speech frames to avoid clipping initial consonants
                    self.frames.extend(self.pre_buffer)
                self.frames.append(frame)
                self.silent = 0
            else:
                self.pre_buffer.append(frame)
                if self.frames:
                    self.frames.append(frame)
                    self.silent += 1
                    if self.silent >= self.silence_limit:
                        self._flush()

            if len(self.frames) >= self.max_frames:
                self._flush()

    def _flush(self) -> None:
        speech_frames_count = len(self.frames) - self.silent
        if speech_frames_count >= self.min_frames and self.started is not None:
            # Trim excess trailing silence (keep ~90ms for natural decay)
            trim = max(0, self.silent - 3)
            active_frames = self.frames[:-trim] if trim > 0 else self.frames
            if active_frames:
                audio = np.concatenate(active_frames).astype(np.float32) / 32768.0
                self.out_q.put(Utterance(self.source, audio, self.started))
        self.frames.clear()
        self.silent = 0
        self.started = None

    def reset(self) -> None:
        """Clear all buffered frames and reset state (used when muted/disabled)."""
        self.frames.clear()
        self.pending = np.zeros(0, dtype=np.int16)
        self.silent = 0
        self.started = None


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
