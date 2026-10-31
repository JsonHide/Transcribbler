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
                    if self.translator and self.output_mode in ("translate", "all"):
                        if lang == "en":
                            english = text
                        else:
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
