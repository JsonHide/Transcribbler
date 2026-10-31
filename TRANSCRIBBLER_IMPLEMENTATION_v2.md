# Transcribbler – Implementation Plan (Version 2.0)

> *Transcribbler: it listens, it scribbles. English, Cantonese and Mandarin from your mic and your speakers, written to a text file.*

A live speech-to-text tool for Windows (CPU-only, no NVIDIA GPU required).

---

## What's New in Version 2.0 (Changelog)

This document addresses all architectural, signal processing, and runtime issues discovered in Version 1:

1. **Fixed Model Download & Folder Paths:** Corrected the model download URL and folder layout to fetch the INT8-quantized SenseVoice package (`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`), matching the `model.int8.onnx` target and reducing disk footprint from ~900 MB to ~230 MB.
2. **Fixed Language Detection (Cantonese Fix):** Extracted SenseVoice language tags (`<|yue|>`, `<|zh|>`, `<|en|>`) *before* stripping control tokens. Previously, tags were erased before inspection, causing colloquial Cantonese to be misclassified as Mandarin.
3. **Fixed Windows Console Crashes (`UnicodeEncodeError`):** Reconfigured `sys.stdout` and `sys.stderr` to UTF-8 on Windows, preventing crashes when printing Chinese characters and Pinyin diacritics on standard Windows code pages (`cp1252`/`cp437`).
4. **Clean Audio Resampling & Decimation:** Eliminated transient clicking artifacts caused by running stateless FIR `resample_poly` on 21 ms chunks. Added exact integer 3:1 decimation for 48 kHz (the standard Windows WASAPI rate) and streaming `soxr` support for 44.1 kHz.
5. **VAD Pre-Speech Ring Buffer & Silence Trimming:** Added a ~180 ms ring buffer so initial word onsets/consonants are not clipped by WebRTC VAD lag, and trimmed excess trailing silence to accelerate SenseVoice inference.
6. **Robust Audio Device Management:** Added `p.get_default_wasapi_loopback()`, `--list-devices`, `--mic-device`, and `--speaker-device` flags for users with multiple audio interfaces, Bluetooth headsets, or USB mics.
7. **Graceful Shutdown (Zero Dropped Utterances):** Worker thread now drains all queued audio before exiting when the user presses `Ctrl+C`.
8. **Fixed Google Translate HTML Entities:** Decoded HTML entities (`&#39;`, `&quot;`, `&amp;`) in Google Cloud Translation responses with `html.unescape`.
9. **Environment & Python Version Guidance:** Added explicit setup notes regarding Python 3.10–3.12 compatibility (since `webrtcvad-wheels` and `PyAudioWPatch` lack precompiled wheels for Python 3.13+ on Windows).

---

## 1. Goal

A Python program that runs locally on Windows (no NVIDIA GPU required) and:

1. Captures **microphone** audio (your voice).
2. Captures **system audio** (speaker output: meetings, videos, calls) via WASAPI loopback.
3. Transcribes **English, Cantonese and Mandarin**.
4. Writes a **`.txt` file** using **English characters**:
   - original text,
   - **romanization**: Mandarin → Pinyin, Cantonese → Jyutping,
   - **English translation**, produced by a backend **chosen at startup: offline, Azure, Google, or off**.

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
| Cantonese romanization | **pycantonese** (Jyutping) | Offline. |
| Translation (offline) | **Argos Translate** zh→en (+ **OpenCC** Traditional → Simplified) | Free, runs locally on CPU after a one-time language pack download. |
| Translation (cloud, option 1) | **Azure Translator** REST API (`yue` support) | Dedicated Cantonese support. Free tier available. |
| Translation (cloud, option 2) | **Google Cloud Translation** (Basic v2) REST API (`yue` support) | 500,000 free chars/month, pay-as-you-go thereafter. |

---

## 3. Architecture

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
                                                                transcript_YYYYMMDD_HHMMSS.txt
```

---

## 4. Project Layout

```
transcribbler/
├─ TRANSCRIBBLER_IMPLEMENTATION_v2.md
├─ requirements.txt
├─ transcribbler.py
├─ models/
│  └─ sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/
│     ├─ model.int8.onnx
│     ├─ tokens.txt
│     └─ ...
└─ transcripts/            # auto-created on first run
```

---

## 5. Setup

### 5.1 Prerequisites & Python Environment

> [!IMPORTANT]
> Use **Python 3.10, 3.11, or 3.12 (64-bit)**. 
> Python 3.13 is currently **not recommended** because binary wheels for `webrtcvad-wheels` and `PyAudioWPatch` are not yet prebuilt for 3.13 on Windows and require full Visual Studio C++ build tools.

#### Option A: Using `uv` (Recommended for speed)
```powershell
uv venv --python 3.12
.venv\Scripts\activate
uv pip install -r requirements.txt
```

#### Option B: Standard `venv` + `pip`
```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 5.2 `requirements.txt`

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
```

### 5.3 Download the Speech Model (One-Time)

Download and extract the INT8-quantized SenseVoice model package:

```powershell
mkdir -p models
cd models
curl -L -O https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
tar -xvf sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
rm sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
cd ..
```

Confirm that `models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/model.int8.onnx` exists.

### 5.4 Prepare Translation Backends

#### Offline Translation (Argos Translate)
```powershell
python transcribbler.py --install-offline-pack
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

## 6. Reference Implementation (`transcribbler.py`)

```python
"""
Transcribbler: Live transcription of microphone + system audio (WASAPI loopback) on Windows.
Engine: SenseVoice-Small via sherpa-onnx (int8, CPU). Languages: en, zh, yue.
Translation backends: off / offline (Argos) / azure / google.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import html
import math
import os
from pathlib import Path
import queue
import re
import sys
import threading
from typing import Any, Optional, Tuple

import numpy as np
import pyaudiowpatch as pyaudio
import pycantonese
from pypinyin import Style, lazy_pinyin
import sherpa_onnx
import webrtcvad

try:
    import soxr
except ImportError:
    soxr = None
    from scipy.signal import resample_poly

# Ensure Windows terminal correctly prints UTF-8 (Chinese, Pinyin tone marks, etc.)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

TARGET_SR = 16000
FRAME_MS = 30
FRAME_SAMPLES = TARGET_SR * FRAME_MS // 1000  # 480 samples @ 16 kHz
MODEL_DIR = Path("models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17")
YUE_CHARS = set("嘅咗哋唔係嚟啲冇喺嗰咁啱睇揾")
TAG_RE = re.compile(r"<\|[^|]*\|>")


@dataclass
class Utterance:
    source: str            # "ME" or "OTHERS"
    audio: np.ndarray      # float32, 16 kHz mono normalized [-1.0, 1.0]
    started: datetime


# ---------------------------------------------------------------- VAD segmenter
class Segmenter:
    """Splits continuous 16 kHz int16 stream into clean utterances."""

    def __init__(
        self,
        source: str,
        out_q: queue.Queue[Utterance],
        aggressiveness: int = 2,
        silence_ms: int = 700,
        max_seconds: int = 25,
        min_ms: int = 300,
        pre_speech_ms: int = 180,
    ):
        self.source = source
        self.out_q = out_q
        self.vad = webrtcvad.Vad(aggressiveness)
        self.pending = np.zeros(0, dtype=np.int16)
        self.frames: list[np.ndarray] = []
        self.silent = 0
        self.started: Optional[datetime] = None

        self.silence_limit = silence_ms // FRAME_MS
        self.max_frames = max_seconds * 1000 // FRAME_MS
        self.min_frames = min_ms // FRAME_MS

        # Circular pre-speech buffer to prevent clipping initial consonants
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

            if is_speech:
                if not self.frames:
                    self.started = datetime.now()
                    # Prepend pre-speech frames
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
        # Require enough speech frames (excluding trailing silence)
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


# ---------------------------------------------------------------- Audio Resampling
class AudioResampler:
    """High-fidelity resampler: exact integer decimation for 48kHz, soxr for 44.1kHz."""

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
            # Exact integer averaging (e.g., 48000 -> 16000 takes every 3rd or 3-sample average)
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
        if len(self._buffer) >= 4800:  # ~100 ms buffer
            y = resample_poly(self._buffer, self.up, self.down)
            self._buffer = np.zeros(0, dtype=np.float32)
            return np.clip(y, -32768, 32767).astype(np.int16)
        return np.zeros(0, dtype=np.int16)


# ---------------------------------------------------------------- Audio Capture
def list_devices(p: pyaudio.PyAudio) -> None:
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

            # Convert multi-channel int16 to mono
            x = np.frombuffer(data, dtype=np.int16)
            if self.ch > 1:
                x = x.reshape(-1, self.ch).mean(axis=1).astype(np.int16)

            # Resample and feed
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


# ---------------------------------------------------------------- Speech Recognition
def guess_lang(text: str) -> str:
    """Fallback heuristic when language metadata is absent."""
    if re.search(r"[\u4e00-\u9fff]", text):
        return "yue" if any(c in YUE_CHARS for c in text) else "zh"
    return "en"


class Recognizer:
    def __init__(self, language: str = "auto", threads: int = 4):
        model_file = MODEL_DIR / "model.int8.onnx"
        tokens_file = MODEL_DIR / "tokens.txt"

        if not model_file.exists() or not tokens_file.exists():
            raise RuntimeError(
                f"Model files missing at {MODEL_DIR}.\n"
                "Run the setup command from Section 5.3 to download the INT8 SenseVoice model."
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


# ---------------------------------------------------------------- Romanization
def romanize(text: str, lang: str) -> Optional[str]:
    if lang == "zh":
        return " ".join(lazy_pinyin(text, style=Style.TONE))
    if lang == "yue":
        tokens = [j for _, j in pycantonese.characters_to_jyutping(text) if j]
        return " ".join(tokens) if tokens else None
    return None


# ---------------------------------------------------------------- Translators
class OfflineTranslator:
    """Argos Translate (zh -> en). Converts Traditional to Simplified first."""

    def __init__(self):
        import argostranslate.translate as t
        from opencc import OpenCC

        installed = t.get_installed_languages()
        codes = {l.code for l in installed}
        if not {"zh", "en"} <= codes:
            raise RuntimeError("Offline pack missing. Run: python transcribbler.py --install-offline-pack")

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


def install_offline_pack() -> None:
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


BACKENDS = {
    "offline": OfflineTranslator,
    "azure": AzureTranslator,
    "google": GoogleTranslator,
}


def make_translator(choice: str) -> Tuple[Optional[Any], str]:
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

    if choice == "off":
        return None, "off"

    return BACKENDS[choice](), choice


# ---------------------------------------------------------------- Output & Worker
def format_entry(
    u: Utterance,
    lang: str,
    original: str,
    roman: Optional[str],
    english: str,
    mode: str,
) -> str:
    ts = u.started.strftime("%H:%M:%S")
    lines = [f"[{ts}] [{u.source}] ({lang})"]
    if mode in ("original", "all"):
        lines.append(f"  Text:   {original}")
    if roman and mode in ("roman", "all"):
        tag = "Pinyin" if lang == "zh" else "Jyutping"
        lines.append(f"  {tag}: {roman}")
    if english and mode in ("translate", "all"):
        lines.append(f"  EN:     {english}")
    return "\n".join(lines) + "\n\n"


def worker(
    q: queue.Queue[Utterance],
    rec: Recognizer,
    translator: Optional[Any],
    out_path: Path,
    mode: str,
    stop: threading.Event,
) -> None:
    with open(out_path, "a", encoding="utf-8") as f:
        # Continue processing until stop is flagged AND the queue is drained
        while not stop.is_set() or not q.empty():
            try:
                u = q.get(timeout=0.4)
            except queue.Empty:
                continue

            try:
                original, lang = rec.run(u.audio)
                if not original:
                    continue

                roman = romanize(original, lang)
                english = ""

                if lang == "en":
                    english = original
                elif translator and mode in ("translate", "all"):
                    try:
                        english = translator.translate(original, lang)
                    except Exception as e:
                        english = f"(translation unavailable: {e})"

                entry = format_entry(u, lang, original, roman, english, mode)
                f.write(entry)
                f.flush()
                print(entry, end="", flush=True)
            finally:
                q.task_done()


# ---------------------------------------------------------------- Main
def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribbler: Live multi-source ASR & translation on Windows.")
    ap.add_argument("--translator", default="ask", choices=["ask", "offline", "azure", "google", "off"])
    ap.add_argument("--language", default="auto", choices=["auto", "en", "zh", "yue"])
    ap.add_argument("--output-mode", default="all", choices=["original", "roman", "translate", "all"])
    ap.add_argument("--threads", type=int, default=4, help="CPU threads for ONNX speech recognition")
    ap.add_argument("--no-mic", action="store_true", help="Disable microphone capture")
    ap.add_argument("--no-speaker", action="store_true", help="Disable system speaker loopback capture")
    ap.add_argument("--mic-device", type=int, default=None, help="Device index for microphone")
    ap.add_argument("--speaker-device", type=int, default=None, help="Device index for speaker loopback")
    ap.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    ap.add_argument("--out", default=None, help="Custom output transcript path")
    ap.add_argument("--install-offline-pack", action="store_true", help="Install Argos zh->en offline pack and exit")
    args = ap.parse_args()

    p = pyaudio.PyAudio()

    if args.list_devices:
        list_devices(p)
        p.terminate()
        return

    if args.install_offline_pack:
        install_offline_pack()
        p.terminate()
        return

    try:
        translator, tname = make_translator(args.translator)
    except Exception as e:
        p.terminate()
        raise SystemExit(f"Translator setup error: {e}")

    out = Path(args.out or f"transcripts/transcript_{datetime.now():%Y%m%d_%H%M%S}.txt")
    out.parent.mkdir(parents=True, exist_ok=True)

    print("Loading SenseVoice model...")
    try:
        rec = Recognizer(args.language, args.threads)
    except Exception as e:
        p.terminate()
        raise SystemExit(f"Failed to load speech model: {e}")

    q: queue.Queue[Utterance] = queue.Queue()
    stop = threading.Event()

    worker_thread = threading.Thread(
        target=worker,
        args=(q, rec, translator, out, args.output_mode, stop),
        daemon=True,
    )
    worker_thread.start()

    captures: list[Capture] = []
    try:
        if not args.no_mic:
            mic_dev = (
                p.get_device_info_by_index(args.mic_device)
                if args.mic_device is not None
                else p.get_default_input_device_info()
            )
            captures.append(Capture(p, mic_dev, Segmenter("ME", q)))
            print(f"Mic active: {mic_dev['name']}")

        if not args.no_speaker:
            spk_dev = find_loopback(p, args.speaker_device)
            captures.append(Capture(p, spk_dev, Segmenter("OTHERS", q)))
            print(f"System loopback active: {spk_dev['name']}")

    except Exception as e:
        stop.set()
        p.terminate()
        raise SystemExit(f"Audio device initialization failed: {e}")

    print(f"\nTranscribbler listening (Translation: {tname}). Writing to {out}")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            stop.wait(1.0)
    except KeyboardInterrupt:
        print("\nStopping Transcribbler... draining pending transcriptions...")
    finally:
        # Stop audio input streams first
        for c in captures:
            c.close()
        # Signal worker and wait for queue to drain
        stop.set()
        worker_thread.join(timeout=5.0)
        p.terminate()
        print("Stopped cleanly.")


if __name__ == "__main__":
    main()
```

---

## 7. Usage Examples

```powershell
# List all available mics and loopback endpoints
python transcribbler.py --list-devices

# Interactive startup (selects translation backend at runtime)
python transcribbler.py

# Fully offline meeting transcription (zero data leaves PC)
python transcribbler.py --translator offline

# Cloud translation using Azure Translator
python transcribbler.py --translator azure

# Remote meeting audio only (speaker loopback), force Cantonese, Google translation
python transcribbler.py --no-mic --language yue --translator google --output-mode translate

# Explicitly bind to specific audio device indices
python transcribbler.py --mic-device 1 --speaker-device 14 --translator offline
```

---

## 8. Translation Backend Comparison

| Attribute | Offline (Argos + OpenCC) | Azure Translator | Google Cloud Translation (v2) |
|---|---|---|---|
| **Privacy** | 100% on-device (zero network traffic) | Recognized text sent to Microsoft | Recognized text sent to Google |
| **Cost** | 100% Free | Free tier (2M chars/mo), then pay-per-char | Free tier (500k chars/mo), then pay-per-char |
| **Cantonese (`yue`)** | Converted to Simplified Chinese; basic | Dedicated `yue` model; high quality | Dedicated `yue` model; high quality |
| **Setup** | One-time pack download | Azure resource key + region | GCP project + API key + billing account |
| **Offline capable** | Yes | No (logs `"translation unavailable"`) | No (logs `"translation unavailable"`) |

---

## 9. Limitations & Practical Mitigations

1. **Speaker Echo / Cross-Talk:** If using external speakers, audio from `OTHERS` will be picked up by your microphone and transcribed as `ME`. **Mitigation:** Use a headset.
2. **Code-Switching:** Sentences mixing Cantonese and English phrases (common in HK workplaces) are handled well by SenseVoice, though romanization will skip non-Chinese tokens.
3. **Bluetooth Headsets in Hands-Free Mode:** Bluetooth headsets on Windows often switch sample rates when an input stream is opened. If audio drops out, run `--list-devices` and specify the exact `--mic-device` and `--speaker-device` indices.
