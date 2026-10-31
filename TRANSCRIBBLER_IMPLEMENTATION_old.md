# Transcribbler – Implementation Plan

> *Transcribbler: it listens, it scribbles. English, Cantonese and Mandarin from your mic and your speakers, written to a text file.*

A live speech-to-text tool for Windows (CPU-only, no NVIDIA GPU required).

## 1. Goal

A Python program that runs locally on Windows (no NVIDIA GPU required) and:

1. Captures **microphone** audio (your voice).
2. Captures **system audio** (speaker output: meetings, videos, calls) via WASAPI loopback.
3. Transcribes **English, Cantonese and Mandarin**.
4. Writes a **`.txt` file** using **English characters**:
   - original text,
   - **romanization**: Mandarin → Pinyin, Cantonese → Jyutping,
   - **English translation**, produced by a backend **you choose at startup: offline, Azure, or Google**.

---

## 2. Technology Choices

| Concern | Choice | Why |
|---|---|---|
| Speech recognition | **SenseVoice-Small** run through **sherpa-onnx** (int8, CPU) | Small multilingual model covering Mandarin, Cantonese and English with auto language ID. Fast on CPU and no PyTorch needed. Runs fully offline. |
| Mic capture | **PyAudioWPatch** | One library for mic and loopback. |
| System audio capture | **PyAudioWPatch** WASAPI loopback | Records what plays on your speakers/headset without a virtual cable. |
| Voice activity detection | **webrtcvad-wheels** | Splits the stream into utterances. |
| Resampling | `scipy.signal.resample_poly` | Device rate (44.1/48 kHz) → 16 kHz mono. |
| Mandarin romanization | **pypinyin** | Offline, with tone marks. |
| Cantonese romanization | **pycantonese** (Jyutping) | Offline. |
| Translation (offline) | **Argos Translate** zh→en (+ **OpenCC** to normalize Traditional → Simplified) | Free, runs locally after a one-time language-pack download. |
| Translation (cloud, option 1) | **Azure Translator** REST API (lists Cantonese `yue`) | Dedicated Cantonese support. Free tier available. |
| Translation (cloud, option 2) | **Google Cloud Translation** (Basic v2) REST API (lists Cantonese `yue`) | 500,000 characters/month free, then pay per character. |

> SenseVoice only transcribes; it does not translate. That is why translation is a separate, swappable component.

---

## 3. Architecture

```
 Mic (PyAudioWPatch) ───────┐
                            ├─► resample 16k mono ─► VAD segmenter ─► utterance queue
 Speaker loopback (WASAPI) ─┘      (one per source)                          │
                                                                   Worker thread
                                                   SenseVoice (sherpa-onnx, local CPU)
                                                     text + language (en / zh / yue)
                                                                              │
                              ┌───────────────────────────────┬───────────────┘
                              │                               │
                        romanize (local)              Translator (chosen per run)
                     Pinyin / Jyutping        ┌─────────┬──────┴───┬───────────┐
                                             off     offline     azure       google
                                                  (Argos+OpenCC) (Azure     (Google Cloud
                                                                 Translator) Translation)
                              └───────────────┬───────────────┘
                                              ▼
                              transcript_YYYYMMDD_HHMMSS.txt
```

### Translation backend selection (per run)

| Mode | Flag | Where translation runs | What leaves your PC | Needs |
|---|---|---|---|---|
| **Off** | `--translator off` | – | Nothing | – |
| **Offline** | `--translator offline` | Your CPU (Argos Translate) | Nothing | One-time ~100 MB language-pack download |
| **Azure** | `--translator azure` | Azure Translator | **Recognized text only** (never audio) | Internet + Azure key |
| **Google** | `--translator google` | Google Cloud Translation | **Recognized text only** (never audio) | Internet + Google API key (billing-enabled project) |
| **Ask** (default) | `--translator ask` | – | – | Prompts at startup: 1 = offline, 2 = Azure, 3 = Google, 4 = off |

Speech recognition is always local in every mode. In the cloud modes only the short recognized text of Mandarin/Cantonese utterances is sent for translation. English speech is never translated or sent. If a cloud backend is selected but its key is missing, the program stops at startup with a clear message instead of failing mid-meeting.

---

## 4. Project Layout

```
transcribbler/
├─ IMPLEMENTATION.md
├─ requirements.txt
├─ transcribbler.py
├─ models/
│  └─ sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/
│     ├─ model.int8.onnx
│     └─ tokens.txt
└─ transcripts/            # auto-created
```

---

## 5. Setup

### 5.1 Prerequisites

- Windows 10/11, **Python 3.10–3.12** (64-bit).
- A headset is strongly recommended (see limitations).

### 5.2 Install

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt`

```
sherpa-onnx
PyAudioWPatch
webrtcvad-wheels
numpy
scipy
pypinyin
pycantonese
opencc-python-reimplemented
argostranslate     # only needed for offline translation
requests           # only needed for cloud translation
```

### 5.3 Download the speech model (one time)

```powershell
mkdir models
cd models
curl -L -O https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
tar xf sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
cd ..
```

If the release URL has changed, find the SenseVoice model on the sherpa-onnx "asr-models" release page.

### 5.4 Prepare the translation backend(s) you want

You can prepare all of them and choose per run.

**Offline** (one-time download, then no internet needed):

```powershell
python transcribbler.py --install-offline-pack
```

**Azure Translator**:

1. Create a *Translator* resource in the Azure portal (the free F0 tier gives a monthly character allowance; check current limits).
2. Set the key and region, then reopen the terminal:

```powershell
setx AZURE_TRANSLATOR_KEY "your-key-here"
setx AZURE_TRANSLATOR_REGION "eastasia"   # or "global" for a global resource
```

**Google Cloud Translation**:

1. In the Google Cloud console, create or pick a project, **enable the Cloud Translation API**, and link a billing account (usually required even to use the monthly free allowance).
2. Go to *APIs & Services → Credentials → Create credentials → API key*, then restrict the key to the Cloud Translation API.
3. Set the key, then reopen the terminal:

```powershell
setx GOOGLE_TRANSLATE_API_KEY "your-key-here"
```

4. Recommended: add a budget alert in Google Cloud Billing so unexpected usage is flagged.

Pricing at time of writing: the first 500,000 characters per month are free, then about $20 per million characters for standard text translation. Check Google's pricing page for current figures.

Treat both keys like passwords: never paste them into the script or commit them to Git.

---

## 6. Reference Implementation (`transcribbler.py`)

```python
"""
Transcribbler: live transcription of microphone + system audio (WASAPI loopback) on Windows.
Engine: SenseVoice-Small via sherpa-onnx (CPU). Languages: en, zh (Mandarin), yue (Cantonese).
Translation backend selectable per run: off / offline (Argos) / azure / google.
"""
import argparse
import math
import os
import queue
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
import pycantonese
import sherpa_onnx
import webrtcvad
from pypinyin import Style, lazy_pinyin
from scipy.signal import resample_poly

TARGET_SR = 16000
FRAME_MS = 30
FRAME_SAMPLES = TARGET_SR * FRAME_MS // 1000  # 480 samples
MODEL_DIR = Path("models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")


@dataclass
class Utterance:
    source: str            # "ME" or "OTHERS"
    audio: np.ndarray      # float32, 16 kHz mono
    started: datetime


# ---------------------------------------------------------------- VAD segmenter
class Segmenter:
    """Splits a continuous 16 kHz int16 stream into utterances."""

    def __init__(self, source, out_q, aggressiveness=2,
                 silence_ms=700, max_seconds=25, min_ms=300):
        self.source, self.out_q = source, out_q
        self.vad = webrtcvad.Vad(aggressiveness)
        self.pending = np.zeros(0, dtype=np.int16)
        self.frames, self.silent, self.started = [], 0, None
        self.silence_limit = silence_ms // FRAME_MS
        self.max_frames = max_seconds * 1000 // FRAME_MS
        self.min_frames = min_ms // FRAME_MS

    def feed(self, pcm16: np.ndarray):
        self.pending = np.concatenate([self.pending, pcm16])
        while len(self.pending) >= FRAME_SAMPLES:
            frame, self.pending = self.pending[:FRAME_SAMPLES], self.pending[FRAME_SAMPLES:]
            if self.vad.is_speech(frame.tobytes(), TARGET_SR):
                if not self.frames:
                    self.started = datetime.now()
                self.frames.append(frame)
                self.silent = 0
            elif self.frames:
                self.frames.append(frame)
                self.silent += 1
                if self.silent >= self.silence_limit:
                    self._flush()
            if len(self.frames) >= self.max_frames:
                self._flush()

    def _flush(self):
        if len(self.frames) - self.silent >= self.min_frames:
            audio = np.concatenate(self.frames).astype(np.float32) / 32768.0
            self.out_q.put(Utterance(self.source, audio, self.started))
        self.frames, self.silent = [], 0


# ---------------------------------------------------------------- audio capture
def find_loopback(p):
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    speakers = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if speakers.get("isLoopbackDevice"):
        return speakers
    for dev in p.get_loopback_device_info_generator():
        if speakers["name"] in dev["name"]:
            return dev
    raise RuntimeError("No WASAPI loopback device found for the default speakers.")


class Capture:
    """Opens one input device, converts to 16 kHz mono, feeds a Segmenter."""

    def __init__(self, p, dev, segmenter):
        self.ch = int(dev["maxInputChannels"])
        self.sr = int(dev["defaultSampleRate"])
        g = math.gcd(TARGET_SR, self.sr)
        self.up, self.down = TARGET_SR // g, self.sr // g
        self.segmenter = segmenter
        self.raw = queue.Queue()
        self.stream = p.open(
            format=pyaudio.paInt16, channels=self.ch, rate=self.sr, input=True,
            input_device_index=dev["index"], frames_per_buffer=1024,
            stream_callback=self._callback,
        )
        threading.Thread(target=self._process, daemon=True).start()

    def _callback(self, in_data, frame_count, time_info, status):
        self.raw.put(in_data)               # keep the callback light
        return (None, pyaudio.paContinue)

    def _process(self):
        while True:
            data = self.raw.get()
            x = np.frombuffer(data, dtype=np.int16).reshape(-1, self.ch).mean(axis=1)
            y = resample_poly(x, self.up, self.down)
            self.segmenter.feed(np.clip(y, -32768, 32767).astype(np.int16))


# ---------------------------------------------------------------- speech recognition
YUE_CHARS = set("嘅咗哋唔係嚟啲冇喺嗰咁啱睇揾")
TAG_RE = re.compile(r"<\|[^|]*\|>")


def guess_lang(text):
    """Fallback when the recognizer does not report a usable language."""
    if re.search(r"[\u4e00-\u9fff]", text):
        return "yue" if any(c in YUE_CHARS for c in text) else "zh"
    return "en"


class Recognizer:
    def __init__(self, language="auto", threads=4):
        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(MODEL_DIR / "model.int8.onnx"),
            tokens=str(MODEL_DIR / "tokens.txt"),
            num_threads=threads,
            use_itn=True,                  # inverse text normalization (numbers, punctuation)
            language=language,             # auto | zh | en | yue
            provider="cpu",
        )
        self.forced = None if language == "auto" else language

    def run(self, audio):
        stream = self.rec.create_stream()
        stream.accept_waveform(TARGET_SR, audio)
        self.rec.decode_stream(stream)
        res = stream.result
        text = TAG_RE.sub("", res.text).strip()
        if not text:
            return "", None
        lang = self.forced or TAG_RE.sub(lambda m: m.group(0)[2:-2], getattr(res, "lang", "") or "")
        if lang not in ("en", "zh", "yue"):
            lang = guess_lang(text)
        return text, lang


# ---------------------------------------------------------------- romanization
def romanize(text, lang):
    if lang == "zh":
        return " ".join(lazy_pinyin(text, style=Style.TONE))
    if lang == "yue":
        return " ".join(j for _, j in pycantonese.characters_to_jyutping(text) if j)
    return None


# ---------------------------------------------------------------- translators
class OfflineTranslator:
    """Argos Translate (zh -> en). Cantonese text is normalized to Simplified first."""

    def __init__(self):
        import argostranslate.translate as t
        from opencc import OpenCC
        codes = {l.code for l in t.get_installed_languages()}
        if not {"zh", "en"} <= codes:
            raise RuntimeError("Offline pack missing. Run: python transcribbler.py --install-offline-pack")
        self._t, self._t2s = t, OpenCC("t2s")

    def translate(self, text, lang):
        return self._t.translate(self._t2s.convert(text), "zh", "en")


class AzureTranslator:
    """Azure Translator REST API. Only the recognized text is sent, never audio."""
    URL = "https://api.cognitive.microsofttranslator.com/translate"

    def __init__(self):
        import requests
        self._requests = requests
        self.key = os.environ.get("AZURE_TRANSLATOR_KEY")
        self.region = os.environ.get("AZURE_TRANSLATOR_REGION", "global")
        if not self.key:
            raise RuntimeError("Set AZURE_TRANSLATOR_KEY (and AZURE_TRANSLATOR_REGION).")

    def translate(self, text, lang):
        src = {"zh": "zh-Hans", "yue": "yue"}[lang]
        r = self._requests.post(
            self.URL,
            params={"api-version": "3.0", "from": src, "to": "en"},
            headers={"Ocp-Apim-Subscription-Key": self.key,
                     "Ocp-Apim-Subscription-Region": self.region,
                     "Content-Type": "application/json"},
            json=[{"Text": text}], timeout=10,
        )
        r.raise_for_status()
        return r.json()[0]["translations"][0]["text"]


class GoogleTranslator:
    """Google Cloud Translation (Basic, v2) via REST + API key. Only recognized text is sent."""
    URL = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self):
        import requests
        self._requests = requests
        self.key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
        if not self.key:
            raise RuntimeError("Set GOOGLE_TRANSLATE_API_KEY.")

    def translate(self, text, lang):
        src = {"zh": "zh-CN", "yue": "yue"}[lang]
        r = self._requests.post(
            self.URL,
            headers={"X-goog-api-key": self.key},
            json={"q": text, "source": src, "target": "en", "format": "text"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["data"]["translations"][0]["translatedText"]


def install_offline_pack():
    import argostranslate.package as pkg
    pkg.update_package_index()
    p = next(p for p in pkg.get_available_packages()
             if p.from_code == "zh" and p.to_code == "en")
    pkg.install_from_path(p.download())
    print("Offline zh->en pack installed.")


BACKENDS = {"offline": OfflineTranslator, "azure": AzureTranslator, "google": GoogleTranslator}


def make_translator(choice):
    if choice == "ask":
        print("Translation to English:\n"
              "  1) Offline            (private, local CPU)\n"
              "  2) Azure Translator   (cloud, sends recognized text only)\n"
              "  3) Google Translation (cloud, sends recognized text only)\n"
              "  4) Off")
        choice = {"1": "offline", "2": "azure", "3": "google", "4": "off"}.get(
            input("Select [1-4]: ").strip(), "off")
    if choice == "off":
        return None, "off"
    return BACKENDS[choice](), choice


# ---------------------------------------------------------------- output
def format_entry(u, lang, original, roman, english, mode):
    ts = u.started.strftime("%H:%M:%S")
    lines = [f"[{ts}] [{u.source}] ({lang})"]
    if mode in ("original", "all"):
        lines.append(f"  Text:   {original}")
    if roman and mode in ("roman", "all"):
        lines.append(f"  {'Pinyin' if lang == 'zh' else 'Jyutping'}: {roman}")
    if english and mode in ("translate", "all"):
        lines.append(f"  EN:     {english}")
    return "\n".join(lines) + "\n\n"


def worker(q, rec, translator, out_path, mode, stop):
    with open(out_path, "a", encoding="utf-8") as f:
        while not stop.is_set():
            try:
                u = q.get(timeout=0.5)
            except queue.Empty:
                continue
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
                except Exception as e:                      # network/key/pack problems
                    english = f"(translation unavailable: {e})"
            entry = format_entry(u, lang, original, roman, english, mode)
            f.write(entry)
            f.flush()
            print(entry, end="")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--translator", default="ask", choices=["ask", "offline", "azure", "google", "off"])
    ap.add_argument("--language", default="auto", choices=["auto", "en", "zh", "yue"])
    ap.add_argument("--output-mode", default="all",
                    choices=["original", "roman", "translate", "all"])
    ap.add_argument("--threads", type=int, default=4, help="CPU threads for recognition")
    ap.add_argument("--no-mic", action="store_true")
    ap.add_argument("--no-speaker", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--install-offline-pack", action="store_true")
    args = ap.parse_args()

    if args.install_offline_pack:
        install_offline_pack()
        return

    try:
        translator, tname = make_translator(args.translator)
    except RuntimeError as e:
        raise SystemExit(f"Translator setup failed: {e}")
    out = Path(args.out or f"transcripts/transcript_{datetime.now():%Y%m%d_%H%M%S}.txt")
    out.parent.mkdir(parents=True, exist_ok=True)

    print("Transcribbler starting. Loading speech model...")
    rec = Recognizer(args.language, args.threads)

    q, stop = queue.Queue(), threading.Event()
    threading.Thread(target=worker, args=(q, rec, translator, out, args.output_mode, stop),
                     daemon=True).start()

    p = pyaudio.PyAudio()
    captures = []
    if not args.no_mic:
        captures.append(Capture(p, p.get_default_input_device_info(), Segmenter("ME", q)))
    if not args.no_speaker:
        captures.append(Capture(p, find_loopback(p), Segmenter("OTHERS", q)))

    print(f"Listening (translation: {tname})... writing to {out}  (Ctrl+C to stop)")
    try:
        while True:
            stop.wait(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for c in captures:
            c.stream.stop_stream(); c.stream.close()
        p.terminate()
        print("Stopped.")


if __name__ == "__main__":
    main()
```

> The sherpa-onnx and Argos APIs evolve between releases. If a call fails after installing the latest versions, check the sherpa-onnx SenseVoice Python example and the Argos Translate docs for the current signatures.

---

## 7. Usage

```powershell
# Ask which translation backend to use at startup
python transcribbler.py

# Private: everything stays on this PC
python transcribbler.py --translator offline

# Cloud: Azure Translator
python transcribbler.py --translator azure

# Cloud: Google Cloud Translation
python transcribbler.py --translator google

# Meeting audio only, Cantonese forced, Google translation, translation lines only
python transcribbler.py --no-mic --language yue --translator google --output-mode translate

# No translation, just text + romanization
python transcribbler.py --translator off
```

### Sample output

```
[14:03:22] [OTHERS] (yue)
  Text:   我哋下個禮拜開會
  Jyutping: ngo5 dei6 haa6 go3 lai5 baai3 hoi1 wui2
  EN:     We are meeting next week.

[14:03:31] [ME] (en)
  Text:   Sounds good, I'll send the agenda.
  EN:     Sounds good, I'll send the agenda.
```

---

## 8. Choosing a Translation Backend

| | Offline (Argos) | Azure Translator | Google Cloud Translation |
|---|---|---|---|
| Privacy | Nothing leaves the PC | Recognized text sent to Microsoft | Recognized text sent to Google |
| Cost | Free | Free tier, then pay per character | 500,000 characters/month free, then about $20 per million |
| Cantonese | Treated as Chinese after Traditional→Simplified conversion; rough for colloquial speech | Lists Cantonese (`yue`) | Lists Cantonese (`yue`) |
| Setup | One-time pack download | Azure resource + key + region | Google Cloud project + API key + billing |
| Works without internet | Yes | No (entry shows "translation unavailable") | No (entry shows "translation unavailable") |

Which cloud backend translates colloquial Cantonese better can vary with the speaker and topic. The practical approach is to record a short sample meeting, run it once with `--translator azure` and once with `--translator google`, and compare the `EN:` lines.

Every backend implements the same `translate(text, lang)` method, so adding another provider (DeepL, an LLM API, etc.) means writing one more small class and adding it to `BACKENDS`.

---

## 9. Known Limitations and Mitigations

| Issue | Mitigation |
|---|---|
| **Echo / duplicates**: speakers play into the mic, so the same speech appears as both `ME` and `OTHERS`. | Use a headset. A later enhancement could drop `ME` utterances that closely match an `OTHERS` one within ~2 s. |
| **Cantonese vs Mandarin mix-ups** in auto-detect. | Use `--language yue` or `--language zh` when you know the language. Colloquial-character heuristics act as a fallback. |
| **Code-switching** (English words inside Cantonese sentences) is imperfect. | Acceptable for most meetings; review important transcripts. |
| **Not truly streaming**: text appears after each pause (~0.7 s of silence). | Lower `silence_ms` in `Segmenter`. Raise `--threads` on a many-core CPU. |
| **Offline translation of colloquial Cantonese** is rough. | Use Azure or Google, or treat the Jyutping and original text as the reliable record. |
| **Per-chunk resampling** can add tiny edge artifacts. | Fine for speech; switch to a stateful resampler (`soxr`) if needed. |
| **Jyutping/Pinyin** can be wrong for context-dependent words. | Treat it as a reading aid. |
| **Privacy / consent**: recording meetings and calls. | Get participants' consent where required by law or policy. |

---

## 10. Test Checklist

1. List loopback devices: `python -c "import pyaudiowpatch as p; a=p.PyAudio(); print(list(a.get_loopback_device_info_generator()))"`.
2. Speak English into the mic and check the `ME` entry.
3. Play a Mandarin video, run with `--translator offline`, then check Pinyin and the EN line.
4. Play a Cantonese video, run once with `--language yue --translator azure` and once with `--translator google`, then compare the Jyutping and EN lines.
5. Cloud failure tests: (a) start with `--translator google` and no `GOOGLE_TRANSLATE_API_KEY` set, and confirm a clear startup error; (b) unplug the network or use a wrong key mid-run, then confirm the entry shows "translation unavailable" and the program keeps running.
6. Switch default output device (speakers ↔ headset), restart, and confirm loopback follows it.
7. Run for 30 minutes and confirm the file keeps growing as UTF-8 and CPU/memory stay stable.

---

## 11. Possible Next Steps

- Automatic fallback: try Azure or Google first, then offline when the network or quota fails.
- Echo de-duplication between `ME` and `OTHERS`.
- Speaker diarization for multiple remote participants.
- Device selection flags (`--mic-index`, `--loopback-index`) and a device listing command.
- Better offline translation via a CTranslate2 opus-mt zh→en model.
- Tray icon or GUI with a start/stop hotkey.
