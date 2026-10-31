# Transcribbler

> *It listens, it scribbles.*  
> Real-time multilingual speech-to-text on Windows (CPU-only, no NVIDIA GPU required) capturing both your **microphone** and **system audio / speakers** (via WASAPI loopback) with live translation, romanization, and a modern desktop interface.

---

## Features

- ⚡ **Near-Real-Time Streaming Transcription**:
  - Upgraded from delayed batch chunking to **low-latency streaming recognition (1.5–2.5s target latency)**.
  - Emits live interim snapshots with visual indicator badges (`⏳ ...`) updated in-place every 1.5 seconds.
  - **Drop-stale interim backpressure**: Asynchronous single-slot interim buffering drops outdated interim frames if the recognizer is busy, preventing queue buildup and ensuring the pipeline never falls behind real time.
  - **Adaptive Clause Splitting & Lowest-RMS Carry-Over**: Adaptive micro-pause detection splits long speech naturally at clause boundaries; continuous non-stop speech (up to 12s) splits at the lowest-energy syllable boundary with frame context carry-over to avoid cutting words in half.
- 🎙️ **Dual-Channel Audio Capture**:
  - **Microphone (`ME`)**: Captures your local microphone voice.
  - **System Loopback (`OTHERS`)**: Directly captures speaker and headset audio (meetings, Zoom, Teams, YouTube, browser calls) without requiring virtual audio cables.
- 🌐 **Multilingual Automatic Speech Recognition**:
  - High-accuracy recognition for **English (`en`)**, **Mandarin Chinese (`zh`)**, and **Cantonese (`yue`)** using **SenseVoice-Small** via `sherpa-onnx` (INT8-quantized, CPU-optimized).
- 🔤 **Automatic Romanization**:
  - **Mandarin**: Tone-marked Pinyin (via `pypinyin`).
  - **Cantonese**: Accurate Jyutping romanization (via `pycantonese`).
- 🌍 **Translation Options**:
  - **Off**: Fast transcription & romanization only. Completely suppresses redundant `EN:` translation lines for cleaner output.
  - **Offline (Argos Translate + OpenCC)**: 100% private, on-device translation from Chinese to English with zero network requests.
  - **Cloud (Azure Translator / Google Cloud Translation)**: Dedicated high-quality Cantonese (`yue`) and Mandarin (`zh`) translation to English.
- 🖥️ **Modern Desktop GUI (CustomTkinter)**:
  - **Dual-Column Split View (Default)**: Dedicated side-by-side feed with `ME` on the left and `OTHERS` on the right.
  - **Live Channel Capture Toggles**: Dedicated **`[Disable]` / `[Enable]`** buttons on both `Microphone (ME)` and `Speaker / System (OTHERS)` to instantly pause and resume audio capturing on either channel in real time.
  - **Unified Timeline View**: One-click toggle to a single chronological stream with colored speaker badges.
  - **Source Filtering**: Filter on the fly between **All Sources**, **Microphone Only**, or **Speaker Only** (synchronized across both views).
  - **Live VAD Activity LEDs**: Pulsing visual indicators when speech is actively detected on either channel, backed by an auto-reset watchdog for silent audio streams.
  - **Productivity Tools**: Floating **Always on Top** overlay mode, font size scaling (`A-` / `A+`), quick **📋 Copy** to clipboard, **💾 Save** transcript to text file, and instant **Clear**.
- 💻 **Headless CLI Mode**: Full-featured command-line interface preserving complete terminal compatibility, automated piping support, and graceful `Ctrl+C` interrupt handling in PowerShell.

---

## Project Structure

```
Transcribbler/
├── models/
│   └── sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/
│       ├── model.int8.onnx
│       └── tokens.txt
├── transcripts/                               # Auto-created transcript output directory
├── transcribbler/
│   ├── __init__.py
│   ├── config.py                              # Audio constants, sample rates, paths
│   ├── core/
│   │   ├── __init__.py
│   │   ├── events.py                          # Utterance, TranscriptEntry, AudioStatusEvent
│   │   ├── audio.py                           # Resampler, VAD Segmenter, Capture, Device helpers
│   │   ├── engine.py                          # SenseVoice Recognizer, Romanizers, Translators
│   │   └── session.py                         # TranscriptionSession (threads, queue, safe cleanup)
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── styles.py                          # Design tokens, dark mode colors, fonts
│   │   ├── components.py                      # Utterance formatting and helpers
│   │   └── app.py                             # TranscribblerApp (CustomTkinter UI)
│   └── cli.py                                 # Headless CLI entrypoint (with signal handling)
├── main.py                                    # Master entrypoint (GUI default or --cli)
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Prerequisites & Installation

### 1. Requirements

- **Operating System**: Windows 10 / 11 (64-bit)
- **Python**: Python 3.10 to 3.13 (64-bit)
- **Audio**: Standard microphone and speaker/headset (WASAPI-compatible)

### 2. Environment Setup

Clone or open the repository in PowerShell:

```powershell
# Optional: Create and activate a virtual environment
py -3.12 -m venv .venv
.venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
```

> [!NOTE]
> `argostranslate` is only needed if you wish to use the on-device offline translation backend. If needed, install it via:
> ```powershell
> pip install argostranslate
> python main.py --cli --install-offline-pack
> ```

### 3. Download Speech Model (One-Time)

Download and extract the INT8 SenseVoice model package (~230 MB):

```powershell
mkdir -p models
cd models
curl -L -O https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
tar -xf sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
rm sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
cd ..
```

Ensure `models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/model.int8.onnx` exists.

---

## Quick Start

### 1. Launching Desktop GUI (Default)

Simply run:

```powershell
python main.py
```

- **Start Capture**: Click **▶ Start** to begin listening to your mic and system audio.
- **Channel Mute / Pause**: Click **`[Disable]`** or **`[Enable]`** directly in either the `Microphone (ME)` or `Speaker / System (OTHERS)` header to pause or resume capturing that channel live without stopping the session.
- **Switch Views**: Toggle between **Dual Column** (side-by-side) and **Unified Timeline** (single chronological stream).
- **Source Filter**: Select **Microphone Only** or **Speaker Only** to isolate a single channel.
- **Float Over Apps**: Check **Always on Top** to keep Transcribbler floating beside Zoom, Teams, Google Meet, or video players.
- **Export & Manage**: Use **📋 Copy** to copy text to clipboard, **💾 Save** to export the session to a custom `.txt` file, or **Clear** to reset the window.

### 2. Headless CLI Mode

For automated pipelines, scripts, or terminal workflows:

```powershell
# Interactive startup (prompts for translation backend)
python main.py --cli

# List available audio devices and WASAPI loopback endpoints
python main.py --cli --list-devices

# Meeting transcription (speakers only, forced Cantonese, Azure translation)
python main.py --cli --no-mic --language yue --translator azure --output-mode translate

# Offline-only mode (zero telemetry/cloud usage)
python main.py --cli --translator offline

# Specify custom audio device indices and transcript path
python main.py --cli --mic-device 1 --speaker-device 10 --out transcripts/meeting_notes.txt
```

> [!TIP]
> Press **`Ctrl+C`** at any time to gracefully drain pending transcriptions and stop the CLI.

#### Available CLI Options:
```
  --translator {ask,offline,azure,google,off}  Translation backend (default: ask)
  --language {auto,en,zh,yue}                  Recognition language (default: auto)
  --output-mode {original,roman,translate,all} Fields to output (default: all)
  --threads THREADS                            CPU threads for ONNX ASR (default: 4)
  --no-mic                                     Disable microphone capture
  --no-speaker                                 Disable system loopback capture
  --mic-device MIC_DEVICE                      Input device index for microphone
  --speaker-device SPEAKER_DEVICE              WASAPI loopback device index for speakers
  --list-devices                               List audio devices and exit
  --install-offline-pack                       Download Argos zh->en package and exit
  --out OUT                                    Custom output text file path
```

---

## Cloud Translation Setup (Optional)

If using cloud translation:

- **Azure Translator**:
  ```powershell
  setx AZURE_TRANSLATOR_KEY "your-azure-key"
  setx AZURE_TRANSLATOR_REGION "eastasia"   # or "global"
  ```
- **Google Cloud Translation (Basic v2)**:
  ```powershell
  setx GOOGLE_TRANSLATE_API_KEY "your-google-api-key"
  ```

---

## Output Format

Transcripts are written to both the interface and `transcripts/transcript_YYYYMMDD_HHMMSS.txt`:

```text
[14:02:11] [ME] (yue)
  Text:     唔該大家睇睇今日個報告
  Jyutping: m4 goi1 daai6 gaa1 tai2 tai2 gam1 jat6 go3 bou3 gou3
  EN:       Please everyone take a look at today's report.

[14:02:15] [OTHERS] (en)
  Text:     Sure, let me share the slide deck on my screen.

[14:02:28] [OTHERS] (zh)
  Text:     好的，我们现在开始讨论第二项议题
  Pinyin:   hǎo de, wǒ men xiàn zài kāi shǐ tǎo lùn dì èr xiàng yì tí
  EN:       Alright, let's now discuss the second agenda item.
```

*(Note: When Translation is set to `off`, the `EN:` translation lines are completely omitted for cleaner transcripts).*

---

## Release Highlights

- **Near-Real-Time Streaming Transcription (v0.5.0)**: Upgraded from 25-second delayed batch chunking to streaming transcription with 1.5–2.5s responsiveness. Features in-place GUI interim text replacement (`⏳ ...`), drop-stale interim backpressure preventing worker backlog, two-tier adaptive clause segmentation, and lowest-RMS syllable splitting with frame carry-over to eliminate mid-word cuts.
- **Channel Capture Toggles (v0.4.0)**: Added live **`[Disable]` / `[Enable]`** buttons in the Microphone and Speaker headers to pause and resume audio capturing independently at the hardware/audio callback level.
- **Graceful CLI Shutdown (v0.3.0)**: Fixed PowerShell `Ctrl+C` interruption by converting the uninterruptible wait into a periodic polling loop and adding Windows `SIGBREAK` signal mapping.
- **Cleaner Transcripts when Translation is Off (v0.2.0)**: Suppressed redundant `EN:` duplicate lines when Translate is set to `off`.
- **Repository Optimization (v0.3.0)**: Streamlined git repository by excluding internal implementation markdowns via `.gitignore`.
- **Desktop UI Enhancements (v0.1.0)**: Added Dual-Column view, Unified Timeline view, dynamic font scaling, copy/save transcript buttons, and live VAD indicators with idle auto-reset.

---

## Practical Tips

1. **Headset Recommendation**: When capturing both microphone and speaker audio simultaneously, wear a headset to avoid external speaker audio bleeding into your microphone.
2. **WASAPI Loopback Behavior**: Windows stops sending loopback frames when no application is emitting sound. Transcribbler handles this gracefully with an automatic VAD activity watchdog.
3. **Bluetooth Headsets**: If using a Bluetooth headset, verify sample rates with `python main.py --cli --list-devices` and select the appropriate interface from the GUI dropdown or CLI flag.

---

## License

MIT License. See individual model licenses in `models/` for SenseVoice usage terms.
