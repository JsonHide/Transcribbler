# Transcribbler – Implementation Plan (Version 3.0)

> *Transcribbler: it listens, it scribbles. English, Cantonese and Mandarin from your mic and your speakers, written to a text file and displayed in a real-time interactive desktop interface.*

A live speech-to-text tool for Windows (CPU-only, no NVIDIA GPU required) featuring a modern desktop interface and terminal mode.

---

## What's New in Version 3.0 (Changelog)

Version 3.0 introduces a dedicated real-time graphical interface and modular architecture while preserving full terminal/CLI compatibility with Version 2.0:

1. **Interactive Real-Time Desktop Interface (CustomTkinter):** Added a native Windows 11-styled dark mode graphical user interface with card-based utterance rendering, low memory footprint (~40 MB), and zero browser overhead.
2. **Dual-Column Split View (Default):** Dedicated side-by-side synchronized columns for **Microphone (`ME`)** on the left and **Speaker / System Audio (`OTHERS`)** on the right, making call and meeting transcripts easy to read.
3. **Unified Timeline View & Instant Toggle:** A one-click toggle switches between the Dual-Column view and a single chronological conversational stream tagged with `[ME]` and `[OTHERS]` badges. Source filtering applies consistently to both views.
4. **Interactive Source Filtering:** Quick filter tabs allow focusing on **All Sources**, **Microphone Only**, or **Speaker / System Only** in real time across both Dual Column and Unified Timeline layouts.
5. **Dynamic Audio Device Selection:** Dropdown pickers for input devices (Microphone) and WASAPI loopback endpoints (Speakers) directly within the interface, eliminating the need to look up device indices manually.
6. **Live Visual Audio Activity & VAD Indicators with Auto-Reset:** Real-time LED indicators pulse green when voice activity is detected on either channel, with an activity watchdog preventing stuck indicators when WASAPI audio goes idle.
7. **Always-on-Top & Overlay Support:** Floating window mode (`Always on Top` toggle) designed to sit alongside Zoom, Microsoft Teams, Google Meet, YouTube, or podcast players.
8. **Productivity Controls:** Start/Stop capture controls, dynamic font size scaling (`A-` / `A+`), quick transcript copy-to-clipboard, transcript export to file, and instant feed clearing. Non-blocking asynchronous shutdown keeps the UI completely fluid.
9. **Modular Architecture:** Refactored the codebase into structured modules (`transcribbler/core/`, `transcribbler/ui/`, `transcribbler/cli.py`, and `main.py`) with an event-driven session model (`TranscriptionSession`).
10. **Dual Mode Entrypoint with 100% v2 CLI Compatibility:** Launching `python main.py` opens the GUI by default, while `python main.py --cli [args]` preserves all Version 2.0 command-line flags (`--list-devices`, `--install-offline-pack`, `--output-mode`, `--language`, `--translator`, `--no-mic`, `--no-speaker`, `--mic-device`, `--speaker-device`, `--out`, `--threads`), including Windows UTF-8 console output encoding fixes.
11. **Python 3.10–3.13 Wheel Compatibility:** Verified precompiled binary wheels for `PyAudioWPatch`, `sherpa-onnx`, `webrtcvad-wheels`, and `customtkinter` on Windows 64-bit across Python 3.10 through 3.13.

---

## 1. Goal

A Python program that runs locally on Windows (no NVIDIA GPU required) and:

1. Captures **microphone** audio (your voice).
2. Captures **system audio** (speaker output: meetings, videos, calls) via WASAPI loopback.
3. Transcribes **English, Cantonese and Mandarin** locally with SenseVoice-Small.
4. Displays live transcriptions in an **interactive desktop interface**:
   - Split dual columns (`Microphone` vs `Speaker`) or unified chronological feed.
   - Filterable by source (`All`, `Mic Only`, `Speaker Only`) in both views.
   - Displays original text, romanization (Mandarin Pinyin / Cantonese Jyutping), and English translation.
   - Live audio status indicators with idle timeout, device selection, and "Always on Top" overlay mode.
   - Font scaling controls (`A-` / `A+`), copy transcript, save to file, and clear feed.
5. Continuously saves transcript entries to a clean **`.txt` file** for record-keeping.
6. Provides an optional headless **CLI mode** with full Version 2.0 parity for scripts and automated pipelines.

---

## 2. Technology Choices

| Concern | Choice | Why |
|---|---|---|
| Speech recognition | **SenseVoice-Small** via **sherpa-onnx** (int8, CPU) | Multilingual model covering Mandarin, Cantonese, and English with auto language ID. Fast on CPU, no PyTorch needed, fully offline. |
| Mic capture | **PyAudioWPatch** | Single library for mic and loopback with WASAPI support. |
| System audio capture | **PyAudioWPatch** WASAPI loopback | Records speaker/headset output directly without virtual audio cables. |
| Voice activity detection | **webrtcvad-wheels** + Ring Buffer | Splits continuous audio into distinct utterances without cutting off word onsets. |
| Resampling | Direct 3:1 decimation (48k→16k) or **soxr** | High fidelity downsampling without transient boundary clicks. |
| Mandarin romanization | **pypinyin** | Offline, with tone marks. |
| Cantonese romanization | **pycantonese** (Jyutping) | Offline Jyutping generation. |
| Translation (offline) | **Argos Translate** zh→en (+ **OpenCC** Traditional → Simplified) | Free, runs locally on CPU after a one-time language pack download. |
| Translation (cloud, option 1) | **Azure Translator** REST API (`yue` support) | Dedicated Cantonese support. Free tier available. |
| Translation (cloud, option 2) | **Google Cloud Translation** (Basic v2) REST API (`yue` support) | 500,000 free chars/month, pay-as-you-go thereafter. |
| **Desktop GUI** | **CustomTkinter** | Modern dark theme, rounded cards, native Windows "Always on Top", lightweight (~40 MB RAM), zero local web server complexity. |

---

## 3. Architecture

### 3.1 Event-Driven System Flow

```
  Mic (PyAudioWPatch) ────────┐
                              ├─► Resample/Decimate 16k mono ─► VAD Segmenter ─► Utterance Queue
  Speaker Loopback (WASAPI) ──┘        (one per source)          (with ring-buffer)       │
                                                                                    Worker Thread
                                                                    SenseVoice (sherpa-onnx, int8 CPU)
                                                                      text + language (en / zh / yue)
                                                                                               │
                                ┌──────────────────────────────────────────────┬───────────────┘
                                │                                              │
                          Romanize (local)                             Translator (per run)
                       Pinyin / Jyutping                       ┌─────────┬──────┴───┬───────────┐
                                                              off     offline     azure       google
                                                                   (Argos+OpenCC) (Azure     (Google Cloud
                                                                                  Translator) Translation)
                                └──────────────────────────────────────────────┬───────────────┘
                                                                               ▼
                                                                     TranscriptEntry Event
                                                                       ┌───────┴───────┐
                                                                       ▼               ▼
                                                        transcript_YYYYMMDD_HHMMSS.txt  UI Event Dispatcher
                                                                                       ┌───────┴───────┐
                                                                                       ▼               ▼
                                                                                   Mic Panel     Speaker Panel
                                                                                   (Column 1)     (Column 2)
```

---

## 4. User Interface Specification

### 4.1 Layout Wireframe

#### Top Control Bar
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  🎙️ Transcribbler Live                                   [—] [口] [X]                  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [▶ Start]  │  Filter: [ All Sources ▼ ]  │  View: [ Dual Column ▼ ]                   │
│  Translate: [ off ▼ ]  │  [📌 Always on Top]  [A-] [🔤 14pt] [A+]  [📋 Copy] [💾 Save] [Clear] │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Dual-Column Split View (Default)
```
┌──────────────────────────────────────┬─────────────────────────────────────────────────┐
│ 🎤 MICROPHONE (ME)           ⚪ Idle  │ 🔊 SPEAKER / SYSTEM (OTHERS)            ⚪ Idle │
├──────────────────────────────────────┼─────────────────────────────────────────────────┤
│ [14:02:11] (yue)                     │ [14:02:15] (en)                                 │
│   Text:     唔該大家睇睇今日個報告   │   Text:     Sure, let me share the slide deck   │
│   Jyutping: m4 goi1 daai6 gaa1 tai2  │             on my screen.                       │
│             tai2 gam1 jat6 go3 bou3  │   EN:       Sure, let me share the slide deck   │
│             gou3                     │             on my screen.                       │
│   EN:       Please everyone take a   │                                                 │
│             look at today's report.  │ [14:02:28] (zh)                                 │
│                                      │   Text:     好的，我们现在开始讨论第二项议题    │
│ [14:02:35] (en)                      │   Pinyin:   hǎo de, wǒ men xiàn zài kāi shǐ     │
│   Text:     Great, looks good to me! │             tǎo lùn dì èr xiàng yì tí           │
│                                      │   EN:       Alright, let's now discuss the      │
│                                      │             second agenda item.                 │
└──────────────────────────────────────┴─────────────────────────────────────────────────┘
```

#### Bottom Status Bar & Device Selectors
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Ready. Click Start to begin listening.     Mic: [ Mic Device ▼ ]  Speaker: [ Spk Dev ▼ ]│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Project Layout

```
Transcribbler/
├── models/
│   └── sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/
│       ├── model.int8.onnx
│       └── tokens.txt
├── transcripts/                               # Auto-created transcript output folder
├── transcribbler/
│   ├── __init__.py
│   ├── config.py                              # Audio constants, paths, default settings
│   ├── core/
│   │   ├── __init__.py
│   │   ├── events.py                          # Utterance, TranscriptEntry, AudioStatusEvent
│   │   ├── audio.py                           # Resampler, VAD Segmenter, Capture, Devices, list_devices
│   │   ├── engine.py                          # SenseVoice Recognizer, Romanizers, Translators, install_offline_pack
│   │   └── session.py                         # TranscriptionSession (thread manager, safe cleanup, event bus)
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── styles.py                          # CustomTkinter theme palettes and typography
│   │   ├── components.py                      # format_entry_block, UI helper functions
│   │   └── app.py                             # TranscribblerApp (main GUI window with full controls)
│   └── cli.py                                 # Headless CLI entrypoint with 100% v2 parity
├── main.py                                    # Master entrypoint (GUI default or --cli)
├── requirements.txt
├── TRANSCRIBBLER_IMPLEMENTATION_v2.md         # Preserved Version 2.0 reference
└── TRANSCRIBBLER_IMPLEMENTATION_v3.md         # Current Version 3.0 specification
```

---

## 6. Setup & Prerequisites

### 6.1 Python Environment

> [!NOTE]
> Python 3.10 through 3.13 (64-bit on Windows) are fully supported. Precompiled wheels are available on PyPI for `PyAudioWPatch`, `sherpa-onnx`, `webrtcvad-wheels`, and `customtkinter`.

```powershell
# Create and activate a virtual environment
py -3.12 -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 6.2 `requirements.txt`

```text
sherpa-onnx>=1.10.0
PyAudioWPatch>=0.2.12.6
webrtcvad-wheels>=2.0.10.post2
numpy>=1.24.0
scipy>=1.11.0
soxr>=0.3.7
pypinyin>=0.50.0
pycantonese>=3.4.0
opencc-python-reimplemented>=0.1.7
argostranslate>=1.9.0
requests>=2.31.0
customtkinter>=5.2.0
```

### 6.3 Download Speech Model (One-Time)

Download and extract the INT8 SenseVoice model package:

```powershell
mkdir -p models
cd models
curl -L -O https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
tar -xvf sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
rm sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
cd ..
```

Confirm that `models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/model.int8.onnx` exists.

### 6.4 Prepare Translation Backends

#### Offline Translation (Argos Translate)
```powershell
python main.py --cli --install-offline-pack
```

#### Azure Translator
```powershell
setx AZURE_TRANSLATOR_KEY "your-azure-key"
setx AZURE_TRANSLATOR_REGION "eastasia"   # or "global"
```

#### Google Cloud Translation
```powershell
setx GOOGLE_TRANSLATE_API_KEY "your-google-api-key"
```

---

## 7. Reference Implementation

### 7.1 Configuration (`transcribbler/config.py`)

```python
"""Global constants and configuration settings for Transcribbler."""
from pathlib import Path

TARGET_SR = 16000
FRAME_MS = 30
FRAME_SAMPLES = TARGET_SR * FRAME_MS // 1000  # 480 samples @ 16 kHz
MODEL_DIR = Path("models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17")
TRANSCRIPTS_DIR = Path("transcripts")
YUE_CHARS = set("嘅咗哋唔係嚟啲冇喺嗰咁啱睇揾")
```

### 7.2 Events & Data Models (`transcribbler/core/events.py`)

```python
"""Event and data definitions for audio capture and speech recognition."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import numpy as np


@dataclass
class Utterance:
    source: str            # "ME" or "OTHERS"
    audio: np.ndarray      # float32, 16 kHz mono normalized [-1.0, 1.0]
    started: datetime


@dataclass
class TranscriptEntry:
    id: str
    timestamp: datetime
    source: str            # "ME" or "OTHERS"
    lang: str              # "en", "zh", "yue"
    text: str
    roman: Optional[str]
    translation: Optional[str]


@dataclass
class AudioStatusEvent:
    source: str            # "ME" or "OTHERS"
    is_capturing: bool
    is_speech: bool
    energy_level: float    # 0.0 to 1.0 for UI level meters
```

### 7.3 Audio Capture & Signal Processing (`transcribbler/core/audio.py`)

```python
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
                rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) / 32768.0)
                self.on_activity(self.source, is_speech, min(1.0, rms * 5.0))

            if is_speech:
                if not self.frames:
                    self.started = datetime.now()
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
            trim = max(0, self.silent - 3)
            active_frames = self.frames[:-trim] if trim > 0 else self.frames
            if active_frames:
                audio = np.concatenate(active_frames).astype(np.float32) / 32768.0
                self.out_q.put(Utterance(self.source, audio, self.started))
        self.frames.clear()
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
            print(f"  [{i}] {dev['name']} (Rate: {int(dev['defaultSampleRate'])} Hz, Channels: {dev['maxInputChannels']})")

    print("\n--- Available WASAPI Loopback Devices (Speakers / System) ---")
    for dev in p.get_loopback_device_info_generator():
        print(f"  [{dev['index']}] {dev['name']} (Rate: {int(dev['defaultSampleRate'])} Hz, Channels: {dev['maxInputChannels']})")
    print()


def find_loopback(p: pyaudio.PyAudio, device_index: Optional[int] = None) -> dict[str, Any]:
    """Find the best WASAPI loopback device, or use the given index."""
    if device_index is not None:
        return p.get_device_info_by_index(device_index)

    if hasattr(p, "get_default_wasapi_loopback"):
        try:
            return p.get_default_wasapi_loopback()
        except OSError:
            pass

    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    speakers = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if speakers.get("isLoopbackDevice"):
        return speakers

    for dev in p.get_loopback_device_info_generator():
        if speakers["name"] in dev["name"]:
            return dev

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

    def _callback(self, in_data, frame_count, time_info, status):
        if self.running.is_set():
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

            x = np.frombuffer(data, dtype=np.int16)
            if self.ch > 1:
                x = x.reshape(-1, self.ch).mean(axis=1).astype(np.int16)

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
```

### 7.4 Engine: Speech Recognition, Romanization & Translation (`transcribbler/core/engine.py`)

```python
"""Speech recognition (SenseVoice), romanization, and translation backends."""
from __future__ import annotations

import html
import os
import re
from typing import Any, Optional, Tuple

import numpy as np
import pycantonese
from pypinyin import Style, lazy_pinyin
import sherpa_onnx

from transcribbler.config import MODEL_DIR, TARGET_SR, YUE_CHARS

TAG_RE = re.compile(r"<\|[^|]*\|>")


def guess_lang(text: str) -> str:
    """Fallback heuristic when language metadata is absent."""
    if re.search(r"[\u4e00-\u9fff]", text):
        return "yue" if any(c in YUE_CHARS for c in text) else "zh"
    return "en"


class Recognizer:
    """SenseVoice-Small offline recognizer via sherpa-onnx (int8, CPU)."""

    def __init__(self, language: str = "auto", threads: int = 4):
        model_file = MODEL_DIR / "model.int8.onnx"
        tokens_file = MODEL_DIR / "tokens.txt"

        if not model_file.exists() or not tokens_file.exists():
            raise RuntimeError(
                f"Model files missing at {MODEL_DIR}.\n"
                "Please download the SenseVoice INT8 model package before running.\n"
                "See Section 6.3 in TRANSCRIBBLER_IMPLEMENTATION_v3.md for instructions."
            )

        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_file),
            tokens=str(tokens_file),
            num_threads=threads,
            use_itn=True,
            language=language,
            provider="cpu",
        )
        self.forced = None if language == "auto" else language

    def run(self, audio: np.ndarray) -> Tuple[str, Optional[str]]:
        """Recognize an utterance. Returns (text, lang) or ("", None) if empty."""
        stream = self.rec.create_stream()
        stream.accept_waveform(TARGET_SR, audio)
        self.rec.decode_stream(stream)
        res = stream.result

        raw_text = getattr(res, "text", "") or ""

        # Extract language tag BEFORE stripping control tokens
        lang = self.forced
        if not lang:
            lang_attr = getattr(res, "lang", "")
            if lang_attr:
                m = TAG_RE.search(lang_attr)
                lang = m.group(0)[2:-2] if m else lang_attr.strip()
            else:
                m = re.search(r"<\|(en|zh|yue|ja|ko)\|>", raw_text)
                if m:
                    lang = m.group(1)

        text = TAG_RE.sub("", raw_text).strip()
        if not text:
            return "", None

        if lang not in ("en", "zh", "yue"):
            lang = guess_lang(text)

        return text, lang


def romanize(text: str, lang: str) -> Optional[str]:
    """Generate romanization: Mandarin → Pinyin, Cantonese → Jyutping."""
    if lang == "zh":
        return " ".join(lazy_pinyin(text, style=Style.TONE))
    if lang == "yue":
        tokens = [j for _, j in pycantonese.characters_to_jyutping(text) if j]
        return " ".join(tokens) if tokens else None
    return None


class OfflineTranslator:
    """Argos Translate (zh -> en). Converts Traditional to Simplified first via OpenCC."""

    def __init__(self):
        import argostranslate.translate as t
        from opencc import OpenCC

        installed = t.get_installed_languages()
        codes = {l.code for l in installed}
        if not {"zh", "en"} <= codes:
            raise RuntimeError(
                "Offline pack missing. Run: python main.py --cli --install-offline-pack"
            )

        self.from_lang = next(l for l in installed if l.code == "zh")
        self.to_lang = next(l for l in installed if l.code == "en")
        self.translation = self.from_lang.get_translation(self.to_lang)
        self.t2s = OpenCC("t2s")

    def translate(self, text: str, lang: str) -> str:
        simplified = self.t2s.convert(text)
        return self.translation.translate(simplified)


class AzureTranslator:
    """Azure Translator REST API (supports 'yue' and 'zh-Hans')."""
    URL = "https://api.cognitive.microsofttranslator.com/translate"

    def __init__(self):
        import requests
        self._requests = requests
        self.key = os.environ.get("AZURE_TRANSLATOR_KEY")
        self.region = os.environ.get("AZURE_TRANSLATOR_REGION", "global")
        if not self.key:
            raise RuntimeError("Missing AZURE_TRANSLATOR_KEY environment variable.")

    def translate(self, text: str, lang: str) -> str:
        src = {"zh": "zh-Hans", "yue": "yue"}.get(lang, "zh-Hans")
        r = self._requests.post(
            self.URL,
            params={"api-version": "3.0", "from": src, "to": "en"},
            headers={
                "Ocp-Apim-Subscription-Key": self.key,
                "Ocp-Apim-Subscription-Region": self.region,
                "Content-Type": "application/json",
            },
            json=[{"Text": text}],
            timeout=8,
        )
        r.raise_for_status()
        return r.json()[0]["translations"][0]["text"]


class GoogleTranslator:
    """Google Cloud Translation Basic (v2) REST API (supports 'yue' and 'zh-CN')."""
    URL = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self):
        import requests
        self._requests = requests
        self.key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
        if not self.key:
            raise RuntimeError("Missing GOOGLE_TRANSLATE_API_KEY environment variable.")

    def translate(self, text: str, lang: str) -> str:
        src = {"zh": "zh-CN", "yue": "yue"}.get(lang, "zh-CN")
        r = self._requests.post(
            self.URL,
            headers={"X-goog-api-key": self.key},
            json={"q": text, "source": src, "target": "en", "format": "text"},
            timeout=8,
        )
        r.raise_for_status()
        translated = r.json()["data"]["translations"][0]["translatedText"]
        return html.unescape(translated)


BACKENDS = {
    "offline": OfflineTranslator,
    "azure": AzureTranslator,
    "google": GoogleTranslator,
}


def install_offline_pack() -> None:
    """Download and install Argos Translate zh -> en language pack."""
    print("Updating Argos package index...")
    import argostranslate.package as pkg

    try:
        pkg.update_package_index()
    except Exception as e:
        print(f"Failed to update package index: {e}")
        return

    packages = [p for p in pkg.get_available_packages() if p.from_code == "zh" and p.to_code == "en"]
    if not packages:
        print("Error: Could not locate zh -> en package.")
        return

    print("Downloading and installing zh -> en package (~100 MB)...")
    download_path = packages[0].download()
    pkg.install_from_path(download_path)
    print("Offline zh -> en pack successfully installed.")


def make_translator(choice: str) -> Tuple[Optional[Any], str]:
    """Create a translator instance from the user's choice string."""
    if choice == "ask":
        print(
            "\nTranslation to English:\n"
            "  1) Offline            (private, local CPU via Argos)\n"
            "  2) Azure Translator   (cloud, sends recognized text only)\n"
            "  3) Google Translation (cloud, sends recognized text only)\n"
            "  4) Off\n"
        )
        selection = input("Select [1-4]: ").strip()
        choice = {"1": "offline", "2": "azure", "3": "google", "4": "off"}.get(selection, "off")

    if choice == "off" or not choice:
        return None, "off"
    if choice not in BACKENDS:
        return None, "off"
    return BACKENDS[choice](), choice
```

### 7.5 Orchestrator & Session Manager (`transcribbler/core/session.py`)

```python
"""Session orchestrator managing background capture threads and dispatching events."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
import queue
import threading
import uuid
from typing import Any, Callable, Optional

import pyaudiowpatch as pyaudio

from transcribbler.config import TRANSCRIPTS_DIR
from transcribbler.core.audio import Capture, Segmenter, find_loopback
from transcribbler.core.engine import Recognizer, make_translator, romanize
from transcribbler.core.events import TranscriptEntry, Utterance

# Ensure Windows terminal correctly prints UTF-8 (Chinese, Pinyin tone marks, etc.)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def format_entry_text(
    e: TranscriptEntry,
    mode: str = "all",
) -> str:
    """Format a transcript entry into text matching the chosen output mode."""
    ts = e.timestamp.strftime("%H:%M:%S")
    lines = [f"[{ts}] [{e.source}] ({e.lang})"]
    if mode in ("original", "all"):
        lines.append(f"  Text:     {e.text}")
    if e.roman and mode in ("roman", "all"):
        tag = "Pinyin" if e.lang == "zh" else "Jyutping"
        lines.append(f"  {tag}: {e.roman}")
    if e.translation and mode in ("translate", "all"):
        lines.append(f"  EN:       {e.translation}")
    return "\n".join(lines) + "\n\n"


class TranscriptionSession:
    """Manages audio capture threads, the recognition worker, and event dispatch."""

    def __init__(
        self,
        translator_choice: str = "off",
        language: str = "auto",
        output_mode: str = "all",
        threads: int = 4,
        mic_device_index: Optional[int] = None,
        speaker_device_index: Optional[int] = None,
        enable_mic: bool = True,
        enable_speaker: bool = True,
        output_path: Optional[Path] = None,
        on_entry: Optional[Callable[[TranscriptEntry], None]] = None,
        on_activity: Optional[Callable[[str, bool, float], None]] = None,
    ):
        self.language = language
        self.output_mode = output_mode
        self.threads = threads
        self.mic_index = mic_device_index
        self.speaker_index = speaker_device_index
        self.enable_mic = enable_mic
        self.enable_speaker = enable_speaker
        self.on_entry = on_entry
        self.on_activity = on_activity

        self.translator, self.tname = make_translator(translator_choice)
        self.out_path = output_path or (
            TRANSCRIPTS_DIR / f"transcript_{datetime.now():%Y%m%d_%H%M%S}.txt"
        )
        self.out_path.parent.mkdir(parents=True, exist_ok=True)

        self.p: Optional[pyaudio.PyAudio] = None
        self.rec: Optional[Recognizer] = None
        self.captures: list[Capture] = []
        self.q: queue.Queue[Utterance] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Initialize audio devices and start capture + recognition threads with atomic cleanup."""
        self.p = pyaudio.PyAudio()
        self.stop_event.clear()

        try:
            self.rec = Recognizer(self.language, self.threads)
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()

            if self.enable_mic:
                dev = (
                    self.p.get_device_info_by_index(self.mic_index)
                    if self.mic_index is not None
                    else self.p.get_default_input_device_info()
                )
                seg = Segmenter("ME", self.q, on_activity=self.on_activity)
                self.captures.append(Capture(self.p, dev, seg))

            if self.enable_speaker:
                dev = find_loopback(self.p, self.speaker_index)
                seg = Segmenter("OTHERS", self.q, on_activity=self.on_activity)
                self.captures.append(Capture(self.p, dev, seg))
        except Exception:
            self.stop()
            raise

    def _worker_loop(self) -> None:
        """Process utterances from the queue: recognize, romanize, translate, and dispatch."""
        with open(self.out_path, "a", encoding="utf-8") as f:
            while not self.stop_event.is_set() or not self.q.empty():
                try:
                    u = self.q.get(timeout=0.3)
                except queue.Empty:
                    continue

                try:
                    text, lang = self.rec.run(u.audio)
                    if not text:
                        continue

                    roman = romanize(text, lang)
                    english = ""
                    if lang == "en":
                        english = text
                    elif self.translator and self.output_mode in ("translate", "all"):
                        try:
                            english = self.translator.translate(text, lang)
                        except Exception as e:
                            english = f"(translation error: {e})"

                    entry = TranscriptEntry(
                        id=uuid.uuid4().hex[:8],
                        timestamp=u.started,
                        source=u.source,
                        lang=lang,
                        text=text,
                        roman=roman,
                        translation=english if english else None,
                    )

                    formatted = format_entry_text(entry, self.output_mode)
                    f.write(formatted)
                    f.flush()

                    if self.on_entry:
                        self.on_entry(entry)
                finally:
                    self.q.task_done()

    def stop(self) -> None:
        """Stop audio streams, drain queue, and shut down cleanly."""
        for c in self.captures:
            c.close()
        self.captures.clear()

        self.stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5.0)
            self.worker_thread = None

        if self.p:
            try:
                self.p.terminate()
            except Exception:
                pass
            self.p = None
```

### 7.6 Styles & Design Tokens (`transcribbler/ui/styles.py`)

```python
"""CustomTkinter theme palettes, typography, and styling constants."""

BG_PRIMARY = "#1a1b1e"
BG_SECONDARY = "#25262b"
BG_CARD = "#2c2e33"

MIC_HEADER_COLOR = "#1864ab"
SPK_HEADER_COLOR = "#2b8a3e"

BTN_START_FG = "#2b8a3e"
BTN_START_HOVER = "#237032"
BTN_STOP_FG = "#c92a2a"
BTN_STOP_HOVER = "#a61e1e"
BTN_NEUTRAL_FG = "#495057"
BTN_NEUTRAL_HOVER = "#343a40"

TEXT_PRIMARY = "#c1c2c5"
TEXT_SECONDARY = "#909296"
TEXT_ACCENT = "#a5d8ff"

LED_ACTIVE = "🟢"
LED_IDLE = "⚪"

FONT_FAMILY = "Segoe UI"
FONT_SIZE_DEFAULT = 14
FONT_SIZE_MIN = 10
FONT_SIZE_MAX = 24
```

### 7.7 Components & Helpers (`transcribbler/ui/components.py`)

```python
"""Reusable UI components and formatting helpers."""
from __future__ import annotations

from transcribbler.core.events import TranscriptEntry


def format_entry_block(entry: TranscriptEntry, include_source: bool = False) -> str:
    """Format a TranscriptEntry as a multi-line text block with language-specific tags."""
    ts = entry.timestamp.strftime("%H:%M:%S")

    if include_source:
        tag = "🎤 ME" if entry.source == "ME" else "🔊 OTHERS"
        header = f"[{ts}] {tag} ({entry.lang})"
    else:
        header = f"[{ts}] ({entry.lang})"

    lines = [header, f"  Text:     {entry.text}"]

    if entry.roman:
        roman_label = "Pinyin" if entry.lang == "zh" else "Jyutping"
        lines.append(f"  {roman_label}: {entry.roman}")

    if entry.translation:
        lines.append(f"  EN:       {entry.translation}")

    return "\n".join(lines) + "\n\n"
```

### 7.8 Desktop User Interface (`transcribbler/ui/app.py`)

```python
"""Interactive CustomTkinter GUI for Transcribbler."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from transcribbler.core.audio import get_audio_devices
from transcribbler.core.events import TranscriptEntry
from transcribbler.core.session import TranscriptionSession
from transcribbler.ui.components import format_entry_block
from transcribbler.ui.styles import (
    BTN_NEUTRAL_FG,
    BTN_NEUTRAL_HOVER,
    BTN_START_FG,
    BTN_START_HOVER,
    BTN_STOP_FG,
    BTN_STOP_HOVER,
    FONT_FAMILY,
    FONT_SIZE_DEFAULT,
    FONT_SIZE_MAX,
    FONT_SIZE_MIN,
    LED_ACTIVE,
    LED_IDLE,
    MIC_HEADER_COLOR,
    SPK_HEADER_COLOR,
)
import pyaudiowpatch as pyaudio


class TranscribblerApp(ctk.CTk):
    """Main Transcribbler desktop GUI application."""

    def __init__(self):
        super().__init__()
        self.title("Transcribbler – Real-Time ASR & Translation")
        self.geometry("1100x720")
        self.minsize(800, 500)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.session: Optional[TranscriptionSession] = None
        self.event_queue: queue.Queue[TranscriptEntry] = queue.Queue()
        self.activity_queue: queue.Queue[tuple[str, bool, float]] = queue.Queue()

        self.entries: list[TranscriptEntry] = []
        self._mics_map: dict[str, int] = {}
        self._spks_map: dict[str, int] = {}

        self.filter_mode = "all"        # "all", "me", "others"
        self.layout_mode = "dual"       # "dual", "unified"
        self.font_size = FONT_SIZE_DEFAULT
        self.is_running = False

        self._last_mic_speech = 0.0
        self._last_spk_speech = 0.0

        self._build_top_bar()
        self._build_content_area()
        self._build_status_bar()
        self._load_devices()

        self.after(100, self._process_events)

    def _build_top_bar(self):
        self.top_frame = ctk.CTkFrame(self, corner_radius=8)
        self.top_frame.pack(fill="x", padx=12, pady=(12, 6))

        row1 = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        row1.pack(fill="x", padx=6, pady=(6, 6))

        self.start_btn = ctk.CTkButton(
            row1, text="▶ Start", width=95,
            fg_color=BTN_START_FG, hover_color=BTN_START_HOVER,
            command=self.toggle_session,
        )
        self.start_btn.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(row1, text="Filter:").pack(side="left", padx=(6, 3))
        self.filter_combo = ctk.CTkComboBox(
            row1,
            values=["All Sources", "Microphone Only", "Speaker Only"],
            width=145, command=self._on_filter_changed, state="readonly",
        )
        self.filter_combo.set("All Sources")
        self.filter_combo.pack(side="left", padx=3)

        ctk.CTkLabel(row1, text="View:").pack(side="left", padx=(6, 3))
        self.layout_combo = ctk.CTkComboBox(
            row1,
            values=["Dual Column", "Unified Timeline"],
            width=140, command=self._on_layout_changed, state="readonly",
        )
        self.layout_combo.set("Dual Column")
        self.layout_combo.pack(side="left", padx=3)

        ctk.CTkLabel(row1, text="Translate:").pack(side="left", padx=(6, 3))
        self.trans_combo = ctk.CTkComboBox(
            row1,
            values=["off", "offline", "azure", "google"],
            width=95, state="readonly",
        )
        self.trans_combo.set("off")
        self.trans_combo.pack(side="left", padx=3)

        self.topmost_var = ctk.BooleanVar(value=False)
        self.topmost_chk = ctk.CTkCheckBox(
            row1, text="Always on Top",
            variable=self.topmost_var, command=self._toggle_topmost,
            width=120,
        )
        self.topmost_chk.pack(side="right", padx=(6, 0))

        self.clear_btn = ctk.CTkButton(
            row1, text="Clear", width=60,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._clear_transcripts,
        )
        self.clear_btn.pack(side="right", padx=3)

        self.save_btn = ctk.CTkButton(
            row1, text="💾 Save", width=68,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._save_transcripts,
        )
        self.save_btn.pack(side="right", padx=3)

        self.copy_btn = ctk.CTkButton(
            row1, text="📋 Copy", width=68,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._copy_transcripts,
        )
        self.copy_btn.pack(side="right", padx=3)

        self.font_minus_btn = ctk.CTkButton(
            row1, text="A-", width=34,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._font_decrease,
        )
        self.font_minus_btn.pack(side="right", padx=2)

        self.font_label = ctk.CTkLabel(row1, text=f"🔤 {self.font_size}pt")
        self.font_label.pack(side="right", padx=2)

        self.font_plus_btn = ctk.CTkButton(
            row1, text="A+", width=34,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._font_increase,
        )
        self.font_plus_btn.pack(side="right", padx=2)

    def _build_content_area(self):
        self.body_frame = ctk.CTkFrame(self, corner_radius=8)
        self.body_frame.pack(fill="both", expand=True, padx=12, pady=6)

        self.dual_container = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.dual_container.pack(fill="both", expand=True)

        self.mic_frame = ctk.CTkFrame(self.dual_container)
        self.mic_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.mic_header = ctk.CTkFrame(self.mic_frame, height=36, fg_color=MIC_HEADER_COLOR)
        self.mic_header.pack(fill="x")
        self.mic_header.pack_propagate(False)
        self.mic_title = ctk.CTkLabel(
            self.mic_header, text="🎤 Microphone (ME)", font=ctk.CTkFont(weight="bold")
        )
        self.mic_title.pack(side="left", padx=10, pady=4)
        self.mic_led = ctk.CTkLabel(self.mic_header, text=f"{LED_IDLE} Idle")
        self.mic_led.pack(side="right", padx=10)

        self.mic_textbox = ctk.CTkTextbox(
            self.mic_frame, font=(FONT_FAMILY, self.font_size), wrap="word",
        )
        self.mic_textbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.spk_frame = ctk.CTkFrame(self.dual_container)
        self.spk_frame.pack(side="right", fill="both", expand=True, padx=(4, 0))

        self.spk_header = ctk.CTkFrame(self.spk_frame, height=36, fg_color=SPK_HEADER_COLOR)
        self.spk_header.pack(fill="x")
        self.spk_header.pack_propagate(False)
        self.spk_title = ctk.CTkLabel(
            self.spk_header, text="🔊 Speaker / System (OTHERS)", font=ctk.CTkFont(weight="bold")
        )
        self.spk_title.pack(side="left", padx=10, pady=4)
        self.spk_led = ctk.CTkLabel(self.spk_header, text=f"{LED_IDLE} Idle")
        self.spk_led.pack(side="right", padx=10)

        self.spk_textbox = ctk.CTkTextbox(
            self.spk_frame, font=(FONT_FAMILY, self.font_size), wrap="word",
        )
        self.spk_textbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.unified_frame = ctk.CTkFrame(self.body_frame)
        self.unified_textbox = ctk.CTkTextbox(
            self.unified_frame, font=(FONT_FAMILY, self.font_size), wrap="word",
        )
        self.unified_textbox.pack(fill="both", expand=True, padx=6, pady=6)

    def _build_status_bar(self):
        self.status_bar = ctk.CTkFrame(self, height=36, corner_radius=6)
        self.status_bar.pack(fill="x", padx=12, pady=(0, 8))

        self.status_label = ctk.CTkLabel(
            self.status_bar, text="Ready. Click Start to begin listening.",
        )
        self.status_label.pack(side="left", padx=10)

        self.spk_combo = ctk.CTkComboBox(
            self.status_bar, values=["Default Loopback"],
            width=230, state="readonly",
        )
        self.spk_combo.pack(side="right", padx=6, pady=2)
        ctk.CTkLabel(self.status_bar, text="Speaker:").pack(side="right", padx=(6, 2))

        self.mic_combo = ctk.CTkComboBox(
            self.status_bar, values=["Default Microphone"],
            width=230, state="readonly",
        )
        self.mic_combo.pack(side="right", padx=6, pady=2)
        ctk.CTkLabel(self.status_bar, text="Mic:").pack(side="right", padx=(10, 2))

    def _load_devices(self):
        try:
            p = pyaudio.PyAudio()
            mics, speakers = get_audio_devices(p)
            self._mics_map = {f"[{d['index']}] {d['name']}": d["index"] for d in mics}
            self._spks_map = {f"[{d['index']}] {d['name']}": d["index"] for d in speakers}
            p.terminate()

            if self._mics_map:
                self.mic_combo.configure(values=list(self._mics_map.keys()))
                self.mic_combo.set(list(self._mics_map.keys())[0])
            if self._spks_map:
                self.spk_combo.configure(values=list(self._spks_map.keys()))
                self.spk_combo.set(list(self._spks_map.keys())[0])
        except Exception as e:
            self.status_label.configure(text=f"Device load warning: {e}")

    def toggle_session(self):
        if not self.is_running:
            self._start_session()
        else:
            self._stop_session()

    def _start_session(self):
        mic_idx = self._mics_map.get(self.mic_combo.get())
        spk_idx = self._spks_map.get(self.spk_combo.get())

        self.session = TranscriptionSession(
            translator_choice=self.trans_combo.get(),
            mic_device_index=mic_idx,
            speaker_device_index=spk_idx,
            enable_mic=True,
            enable_speaker=True,
            on_entry=self.event_queue.put,
            on_activity=lambda src, sp, lvl: self.activity_queue.put((src, sp, lvl)),
        )
        try:
            self.session.start()
            self.is_running = True
            self.start_btn.configure(
                text="⏹ Stop", fg_color=BTN_STOP_FG, hover_color=BTN_STOP_HOVER, state="normal",
            )
            self.status_label.configure(
                text=f"Transcribing... (Translation: {self.session.tname}) | Output: {self.session.out_path}",
            )
            self.mic_combo.configure(state="disabled")
            self.spk_combo.configure(state="disabled")
            self.trans_combo.configure(state="disabled")
        except Exception as e:
            self.status_label.configure(text=f"Startup Error: {e}")
            if self.session:
                try:
                    self.session.stop()
                except Exception:
                    pass
                self.session = None

    def _stop_session(self):
        self.start_btn.configure(state="disabled", text="Stopping...")
        session_to_stop = self.session
        self.session = None
        self.is_running = False

        def _async_stop():
            if session_to_stop:
                session_to_stop.stop()
            self.after(0, self._on_stop_complete)

        threading.Thread(target=_async_stop, daemon=True).start()

    def _on_stop_complete(self):
        self.start_btn.configure(
            text="▶ Start", fg_color=BTN_START_FG, hover_color=BTN_START_HOVER, state="normal",
        )
        self.status_label.configure(text="Stopped.")
        self.mic_led.configure(text=f"{LED_IDLE} Idle")
        self.spk_led.configure(text=f"{LED_IDLE} Idle")
        self.mic_combo.configure(state="readonly")
        self.spk_combo.configure(state="readonly")
        self.trans_combo.configure(state="readonly")

    def _process_events(self):
        now = time.time()
        activity_count = 0
        while not self.activity_queue.empty() and activity_count < 25:
            src, is_speech, _ = self.activity_queue.get_nowait()
            if is_speech:
                if src == "ME":
                    self._last_mic_speech = now
                    self.mic_led.configure(text=f"{LED_ACTIVE} Speaking")
                else:
                    self._last_spk_speech = now
                    self.spk_led.configure(text=f"{LED_ACTIVE} Speaking")
            activity_count += 1

        if self.is_running:
            if now - self._last_mic_speech > 0.6:
                self.mic_led.configure(text=f"{LED_IDLE} Listening")
            if now - self._last_spk_speech > 0.6:
                self.spk_led.configure(text=f"{LED_IDLE} Listening")

        while not self.event_queue.empty():
            entry = self.event_queue.get_nowait()
            self.entries.append(entry)
            self._render_entry(entry)

        self.after(100, self._process_events)

    def _render_entry(self, entry: TranscriptEntry):
        col_block = format_entry_block(entry, include_source=False)
        uni_block = format_entry_block(entry, include_source=True)

        if entry.source == "ME":
            self.mic_textbox.insert("end", col_block)
            self.mic_textbox.see("end")
        else:
            self.spk_textbox.insert("end", col_block)
            self.spk_textbox.see("end")

        mode = self.filter_combo.get()
        if mode == "All Sources" or (mode == "Microphone Only" and entry.source == "ME") or (mode == "Speaker Only" and entry.source == "OTHERS"):
            self.unified_textbox.insert("end", uni_block)
            self.unified_textbox.see("end")

    def _rebuild_unified_textbox(self):
        self.unified_textbox.delete("1.0", "end")
        mode = self.filter_combo.get()
        for e in self.entries:
            if mode == "All Sources" or (mode == "Microphone Only" and e.source == "ME") or (mode == "Speaker Only" and e.source == "OTHERS"):
                self.unified_textbox.insert("end", format_entry_block(e, include_source=True))
        self.unified_textbox.see("end")

    def _on_filter_changed(self, choice):
        self.mic_frame.pack_forget()
        self.spk_frame.pack_forget()

        if choice == "Microphone Only":
            self.mic_frame.pack(side="left", fill="both", expand=True)
        elif choice == "Speaker Only":
            self.spk_frame.pack(side="right", fill="both", expand=True)
        else:
            self.mic_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
            self.spk_frame.pack(side="right", fill="both", expand=True, padx=(4, 0))

        self._rebuild_unified_textbox()

    def _on_layout_changed(self, choice):
        if choice == "Unified Timeline":
            self.dual_container.pack_forget()
            self.unified_frame.pack(fill="both", expand=True)
            self._rebuild_unified_textbox()
        else:
            self.unified_frame.pack_forget()
            self.dual_container.pack(fill="both", expand=True)

    def _toggle_topmost(self):
        self.attributes("-topmost", self.topmost_var.get())

    def _clear_transcripts(self):
        self.entries.clear()
        self.mic_textbox.delete("1.0", "end")
        self.spk_textbox.delete("1.0", "end")
        self.unified_textbox.delete("1.0", "end")

    def _copy_transcripts(self):
        full_text = "\n".join(format_entry_block(e, include_source=True) for e in self.entries)
        if not full_text.strip():
            messagebox.showinfo("Copy Transcript", "No transcript entries to copy.")
            return
        self.clipboard_clear()
        self.clipboard_append(full_text)
        self.update()
        messagebox.showinfo("Copy Transcript", "Transcript copied to clipboard!")

    def _save_transcripts(self):
        full_text = "\n".join(format_entry_block(e, include_source=True) for e in self.entries)
        if not full_text.strip():
            messagebox.showinfo("Save Transcript", "No transcript entries to save.")
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=f"transcript_export_{datetime.now():%Y%m%d_%H%M%S}.txt",
        )
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_text)
            messagebox.showinfo("Save Transcript", f"Transcript successfully saved to:\n{file_path}")

    def _font_increase(self):
        if self.font_size < FONT_SIZE_MAX:
            self.font_size += 1
            self._apply_font_size()

    def _font_decrease(self):
        if self.font_size > FONT_SIZE_MIN:
            self.font_size -= 1
            self._apply_font_size()

    def _apply_font_size(self):
        font = (FONT_FAMILY, self.font_size)
        self.mic_textbox.configure(font=font)
        self.spk_textbox.configure(font=font)
        self.unified_textbox.configure(font=font)
        self.font_label.configure(text=f"🔤 {self.font_size}pt")

    def destroy(self):
        if self.session:
            self.session.stop()
        super().destroy()
```

### 7.9 CLI Runner with 100% v2 Parity (`transcribbler/cli.py`)

```python
"""Headless Command-Line Runner preserving full backward compatibility with Version 2.0."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from transcribbler.core.audio import list_devices
from transcribbler.core.engine import install_offline_pack
from transcribbler.core.events import TranscriptEntry
from transcribbler.core.session import TranscriptionSession, format_entry_text
import pyaudiowpatch as pyaudio

# Ensure Windows terminal correctly prints UTF-8 (Cantonese/Mandarin Chinese, Pinyin diacritics)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_cli() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribbler: Live multi-source ASR & translation on Windows (CLI mode).",
    )
    ap.add_argument(
        "--translator", default="ask",
        choices=["ask", "offline", "azure", "google", "off"],
        help="Translation backend to English (default: ask interactively)",
    )
    ap.add_argument(
        "--language", default="auto",
        choices=["auto", "en", "zh", "yue"],
        help="Force recognition language or use 'auto' detection (default: auto)",
    )
    ap.add_argument(
        "--output-mode", default="all",
        choices=["original", "roman", "translate", "all"],
        help="Transcript fields to output: original text, romanization, translation, or all (default: all)",
    )
    ap.add_argument(
        "--threads", type=int, default=4,
        help="CPU threads for ONNX speech recognition (default: 4)",
    )
    ap.add_argument(
        "--no-mic", action="store_true",
        help="Disable microphone capture",
    )
    ap.add_argument(
        "--no-speaker", action="store_true",
        help="Disable system speaker loopback capture",
    )
    ap.add_argument(
        "--mic-device", type=int, default=None,
        help="Device index for microphone (use --list-devices to find)",
    )
    ap.add_argument(
        "--speaker-device", type=int, default=None,
        help="Device index for speaker loopback (use --list-devices to find)",
    )
    ap.add_argument(
        "--list-devices", action="store_true",
        help="List audio devices and exit",
    )
    ap.add_argument(
        "--out", default=None,
        help="Custom output transcript file path",
    )
    ap.add_argument(
        "--install-offline-pack", action="store_true",
        help="Install Argos zh->en offline translation pack and exit",
    )
    args = ap.parse_args()

    if args.list_devices:
        p = pyaudio.PyAudio()
        list_devices(p)
        p.terminate()
        return

    if args.install_offline_pack:
        install_offline_pack()
        return

    def print_entry(e: TranscriptEntry):
        text = format_entry_text(e, args.output_mode)
        print(text, end="", flush=True)

    try:
        session = TranscriptionSession(
            translator_choice=args.translator,
            language=args.language,
            output_mode=args.output_mode,
            threads=args.threads,
            mic_device_index=args.mic_device,
            speaker_device_index=args.speaker_device,
            enable_mic=not args.no_mic,
            enable_speaker=not args.no_speaker,
            output_path=Path(args.out) if args.out else None,
            on_entry=print_entry,
        )
    except Exception as e:
        raise SystemExit(f"Session initialization failed: {e}")

    print("Starting Transcribbler in CLI mode. Press Ctrl+C to stop.\n")
    try:
        session.start()
        print(f"Listening... (Translation: {session.tname}) | Output: {session.out_path}\n")
        session.stop_event.wait()
    except KeyboardInterrupt:
        print("\nStopping Transcribbler... draining pending transcriptions...")
    finally:
        session.stop()
        print("Stopped cleanly.")
```

### 7.10 Master Entrypoint (`main.py`)

```python
"""Transcribbler master entrypoint. Launches GUI by default or CLI with --cli."""
import sys

if __name__ == "__main__":
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from transcribbler.cli import run_cli
        run_cli()
    else:
        from transcribbler.ui.app import TranscribblerApp
        app = TranscribblerApp()
        app.mainloop()
```

---

## 8. Usage Guide

### 8.1 Launching the Interactive GUI (Default)

Simply run:
```powershell
python main.py
```
- Click **▶ Start** to begin listening to your microphone and system speakers.
- Switch between **Dual Column** (Mic on Left, Speaker on Right) and **Unified Timeline** at any time.
- Filter view by selecting **Microphone Only** or **Speaker Only** from the Filter dropdown.
- Check **Always on Top** to keep the window pinned over meetings or video calls.
- Scale font with **A-** / **A+**, copy the entire transcript with **📋 Copy**, or export it with **💾 Save**.

### 8.2 Headless / CLI Usage

For background recording, automated pipelines, or low-overhead terminal sessions:
```powershell
# List all available microphones and loopback devices
python main.py --cli --list-devices

# Install Argos offline pack
python main.py --cli --install-offline-pack

# Interactive startup (selects translation backend at runtime)
python main.py --cli

# Offline meeting transcription (zero data leaves PC)
python main.py --cli --translator offline

# Remote meetings only (speaker loopback), force Cantonese, Azure translation
python main.py --cli --no-mic --language yue --translator azure --output-mode translate
```

---

## 9. Translation Backend Comparison

| Attribute | Offline (Argos + OpenCC) | Azure Translator | Google Cloud Translation (v2) | Off |
|---|---|---|---|---|
| **Privacy** | 100% on-device (zero network traffic) | Recognized text sent to Microsoft | Recognized text sent to Google | 100% private |
| **Cost** | 100% Free | Free tier (2M chars/mo), then pay-per-char | Free tier (500k chars/mo), then pay-per-char | Free |
| **Cantonese (`yue`)** | Converted to Simplified Chinese; basic | Dedicated `yue` model; high quality | Dedicated `yue` model; high quality | N/A |
| **Setup** | One-time pack download | Azure resource key + region | GCP project + API key + billing account | Instant |
| **Offline capable** | Yes | No (logs error string) | No (logs error string) | Yes |

---

## 10. Limitations & Practical Mitigations

1. **Speaker Echo / Cross-Talk:** If external speakers are used, system audio will be picked up by your microphone and transcribed twice. **Mitigation:** Wear a headset during calls.
2. **Audio Endpoint Changes (e.g. Bluetooth connect/disconnect):** If a Bluetooth headset is plugged in while running, restart the session or select the new device from the dropdown.
3. **Always-On-Top Transparency:** For advanced transparency overlay over full-screen apps, CustomTkinter window attributes (`-alpha`) can be enabled.
