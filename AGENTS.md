# AGENTS.md — Transcribbler Permanent Rulebook

## 1. Tech Stack & How to Run
- **Platform & Python:** Windows 10/11 (64-bit, CPU-only, WASAPI loopback), Python 3.10–3.13 (local `.venv` uses Python 3.13).
- **Environment & Dependencies:** Managed via `.venv` and `requirements.txt` (`pip install -r requirements.txt`). Activate with `.venv\Scripts\activate` or invoke `.venv\Scripts\python.exe` directly.
- **Run Desktop GUI (default):** `python main.py`
- **Run Headless CLI:** `python main.py --cli` (e.g., `python main.py --cli --language en --translator off`)
- **Utility CLI commands:** `python main.py --cli --list-devices` | `python main.py --cli --install-offline-pack`

## 2. Project Map
- `main.py` — Master entrypoint; routes `--cli` to `transcribbler.cli.run_cli()` and otherwise launches `TranscribblerApp`.
- `transcribbler/__init__.py` — Single source of truth for `__version__`. Never hardcode version numbers elsewhere.
- `transcribbler/config.py` — Global audio constants, model/transcript paths, `APP_VERSION`, and `APP_TITLE`.
- `transcribbler/core/` — Non-UI business logic:
  - `events.py` — Dataclasses (`Utterance`, `TranscriptEntry`, `AudioStatusEvent`).
  - `audio.py` — `AudioResampler`, `Segmenter` (WebRTC VAD + RMS), `Capture`, WASAPI device helpers, and WinMM hot-plug signature.
  - `engine.py` — `Recognizer` (`sherpa-onnx` INT8 CPU), lazy-loaded `romanize()`, and translation backends (`offline`, `azure`, `google`).
  - `session.py` — `TranscriptionSession` thread/queue orchestration, transcript file writing, and `format_entry_text()`.
- `transcribbler/ui/` — CustomTkinter desktop app (`app.py`), theme/typography tokens (`styles.py`), and widgets/formatting (`components.py`). Keep UI logic out of `core/` and ASR/audio logic out of `ui/`.
- `transcribbler/cli.py` — Headless CLI argument parsing, signal handling, and stdout formatting.
- `tests/` — `unittest` suite (`tests/test_*.py`). Put all new automated tests here.
- `models/` & `transcripts/` — Local runtime artifacts (gitignored; never commit).

## 3. Code, Data & Security Guardrails
- **Coding Patterns:**
  - Use `from __future__ import annotations`, standard type hints, and `pathlib.Path` for paths.
  - Always use explicit `encoding="utf-8"` for file I/O and preserve Windows `sys.stdout`/`sys.stderr` UTF-8 reconfiguration.
  - Never block the Tkinter main thread: run model loading, device rescans, and session teardown on daemon threads, and marshal UI updates via `queue.Queue` or `self.after(0, ...)`.
  - Raise `RuntimeError` for missing models, credentials, or audio endpoints. Catch per-utterance translation errors inline so the worker loop never crashes; log non-fatal stream errors to `sys.stderr`.
  - Keep `pycantonese` and `pypinyin` lazy-loaded on first `zh`/`yue` use and preserve LRU caches and persistent `requests.Session()` instances.
- **Output Format:**
  - Transcript files use `transcripts/transcript_YYYYMMDD_HHMMSS.txt` with `[HH:MM:SS] [SOURCE] (lang)` blocks (`Text:`, optional `Pinyin:`/`Jyutping:`, optional `EN:`).
  - When translation is `off`, omit `EN:` lines completely. Never write non-final (`is_final=False`) interims to disk.
- **Security & Secrets:**
  - Never hardcode API keys, credentials, or personal data. Load secrets only from environment variables (`AZURE_TRANSLATOR_KEY`, `AZURE_TRANSLATOR_REGION`, `GOOGLE_TRANSLATE_API_KEY`) or `.env` (keep `.env` in `.gitignore`).
  - Never commit model binaries (`models/`, `*.onnx`), transcripts (`transcripts/`), or local secrets.
- **Dependencies:** Do not add new third-party packages to `requirements.txt` unless explicitly asked.

## 4. Core Business / Domain Logic Invariants
- **Audio Pipeline:** All capture channels resample to 16 kHz mono (`TARGET_SR = 16000`, `FRAME_MS = 30`, `FRAME_SAMPLES = 480`) and emit normalized `float32` `[-1.0, 1.0]` `Utterance` arrays. Preserve remainder samples in `AudioResampler` decimation and bounded drop-oldest buffering (`maxsize=256`) in `Capture.raw_queue`.
- **Dual-Mode Streaming:**
  - GUI mode keeps `enable_interim=True` and default `Segmenter` thresholds (`silence_ms=450`, `soft_max_seconds=5.0`, `soft_silence_ms=150`, `soft_silence_rms_ratio=0.18`, `max_seconds=12.0`).
  - CLI mode sets `enable_interim=False` and low-latency final-only thresholds (`silence_ms=360`, `soft_max_seconds=2.2`, `soft_silence_ms=90`, `soft_silence_rms_ratio=0.25`, `max_seconds=3.5`).
  - Final utterances (`self.q`) always have strict priority over drop-stale interims (`_latest_interim`); supersede and discard interims whose `utterance_id` is already finalized.
- **Dual-Engine ASR Routing:**
  - `language == "en"` routes to `Parakeet-TDT-0.6B-v2` with `Moonshine-Base-EN` fallback (order reversed when `en_engine == "moonshine"`).
  - `language in ("auto", "zh", "yue")` routes to `SenseVoice-Small` (`use_itn=True`). Extract language tags from SenseVoice output *before* stripping `<|...|>` control tokens.
- **Windows PortAudio Hot-Plug:** PortAudio caches hardware lists until every `PyAudio` instance is terminated. Live rescanning/device switching in `TranscriptionSession.reload_audio_devices()` must recycle only `Capture` streams and `PyAudio`, keeping the ASR recognizer, worker thread, and transcript file alive, and matching devices by name (indices shift on hot-plug).

## 5. Verification Before Finishing
Run these commands from the project root after any code change:
```powershell
.venv\Scripts\python.exe -m compileall -q main.py transcribbler tests
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe main.py --cli --version
```
