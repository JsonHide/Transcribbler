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
    try:
        import signal
        signal.signal(signal.SIGBREAK, lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt))
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
        help="Recognition language: 'auto' (SenseVoice multilingual) or 'en' (Parakeet-TDT / Moonshine) (default: auto)",
    )
    ap.add_argument(
        "--en-engine", default="auto",
        choices=["auto", "parakeet", "moonshine"],
        help="Preferred engine when --language=en: 'auto' (Parakeet then Moonshine), 'parakeet', or 'moonshine'",
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
        if not e.is_final:
            return
        text = format_entry_text(e, args.output_mode)
        print(text, end="", flush=True)

    try:
        session = TranscriptionSession(
            translator_choice=args.translator,
            language=args.language,
            en_engine=args.en_engine,
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
        print(
            f"Listening... [ASR: {session.engine_name} | Translation: {session.tname}] "
            f"| Output: {session.out_path}\n"
        )
        while not session.stop_event.is_set():
            session.stop_event.wait(0.5)
    except KeyboardInterrupt:
        print("\nStopping Transcribbler... draining pending transcriptions...")
    finally:
        session.stop()
        print("Stopped cleanly.")
