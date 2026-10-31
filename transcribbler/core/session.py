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
from transcribbler.core.audio import Capture, Segmenter, find_loopback, get_audio_devices
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
        self._interim_lock = threading.Lock()
        self._latest_interim: dict[str, Utterance] = {}
        self._finalized_ids: set[str] = set()
        self._last_interim_source: str = "OTHERS"
        self._work_event = threading.Event()
        self._device_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None

    def _submit_final(self, u: Utterance) -> None:
        """Enqueue a finalized utterance (FIFO) and discard any stale interim for the same ID."""
        with self._interim_lock:
            self._finalized_ids.add(u.utterance_id)
            if len(self._finalized_ids) > 500:
                self._finalized_ids.clear()
                self._finalized_ids.add(u.utterance_id)
            pending = self._latest_interim.get(u.source)
            if pending is not None and pending.utterance_id == u.utterance_id:
                del self._latest_interim[u.source]
        self.q.put(u)
        self._work_event.set()

    def _submit_interim(self, u: Utterance) -> None:
        """Store only the latest interim snapshot per source (drop-stale backpressure)."""
        with self._interim_lock:
            if u.utterance_id in self._finalized_ids:
                return
            self._latest_interim[u.source] = u
        self._work_event.set()

    def _pop_next_interim(self) -> Optional[Utterance]:
        """Pop the next pending interim utterance, alternating sources for fairness."""
        with self._interim_lock:
            if not self._latest_interim:
                return None
            preferred = "ME" if self._last_interim_source == "OTHERS" else "OTHERS"
            if preferred in self._latest_interim:
                self._last_interim_source = preferred
                return self._latest_interim.pop(preferred)
            src, u = next(iter(self._latest_interim.items()))
            self._last_interim_source = src
            del self._latest_interim[src]
            return u

    def _open_capture(self, source: str) -> None:
        """Open a capture stream for 'ME' or 'OTHERS' on the currently selected device."""
        if self.p is None:
            return
        if source == "ME":
            dev = (
                self.p.get_device_info_by_index(self.mic_index)
                if self.mic_index is not None
                else self.p.get_default_input_device_info()
            )
        else:
            dev = find_loopback(self.p, self.speaker_index)

        seg = Segmenter(
            source,
            self.q,
            on_activity=self.on_activity,
            on_final=self._submit_final,
            on_interim=self._submit_interim,
        )
        self.captures.append(Capture(self.p, dev, seg))

    def _open_captures(self) -> None:
        """Open capture streams for all enabled channels."""
        if self.enable_mic:
            self._open_capture("ME")
        if self.enable_speaker:
            self._open_capture("OTHERS")

    def _close_captures(self) -> None:
        for c in self.captures:
            c.close()
        self.captures.clear()

    def start(self) -> None:
        """Initialize audio devices and start capture + recognition threads with atomic cleanup."""
        self.p = pyaudio.PyAudio()
        self.stop_event.clear()
        self._work_event.clear()

        try:
            self.rec = Recognizer(self.language, self.threads)
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()

            with self._device_lock:
                self._open_captures()
        except Exception:
            self.stop()
            raise

    def reload_audio_devices(
        self,
        mic_device_index: Optional[int] = None,
        speaker_device_index: Optional[int] = None,
        mic_name: Optional[str] = None,
        speaker_name: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Re-enumerate audio hardware and reopen capture streams on the chosen devices.

        PortAudio only rescans Windows endpoints after every PyAudio instance is terminated,
        so this closes the active streams, terminates PyAudio, and re-creates it. The
        SenseVoice recognizer, worker thread, and transcript file stay alive throughout.
        Devices may be given by name (preferred, since indices shift after hot-plug) or index;
        unplugged devices fall back to the system default. Returns (mics, speakers).
        """
        with self._device_lock:
            self._close_captures()
            if self.p:
                try:
                    self.p.terminate()
                except Exception:
                    pass
            self.p = pyaudio.PyAudio()
            mics, speakers = get_audio_devices(self.p)

            def _resolve(devices, name, index):
                if name:
                    for d in devices:
                        if d["name"] == name:
                            return d["index"]
                    return None
                return index if index in {d["index"] for d in devices} else None

            self.mic_index = _resolve(mics, mic_name, mic_device_index)
            self.speaker_index = _resolve(speakers, speaker_name, speaker_device_index)

            if self.stop_event.is_set():
                # Session stopped while the refresh was queued: don't leave PortAudio open
                try:
                    self.p.terminate()
                except Exception:
                    pass
                self.p = None
            else:
                for source, enabled in (("ME", self.enable_mic), ("OTHERS", self.enable_speaker)):
                    if not enabled:
                        continue
                    try:
                        self._open_capture(source)
                    except Exception as e:
                        print(f"[Transcribbler] Failed to open {source} device: {e}", file=sys.stderr)
            return mics, speakers

    def _worker_loop(self) -> None:
        """Process finalized (priority FIFO) and interim (drop-stale) utterances."""
        with open(self.out_path, "a", encoding="utf-8") as f:
            while not self.stop_event.is_set() or not self.q.empty():
                u: Optional[Utterance] = None
                from_fifo = False

                try:
                    u = self.q.get_nowait()
                    from_fifo = True
                except queue.Empty:
                    if not self.stop_event.is_set():
                        u = self._pop_next_interim()

                if u is None:
                    self._work_event.wait(timeout=0.15)
                    self._work_event.clear()
                    continue

                try:
                    text, lang = self.rec.run(u.audio)
                    if not text:
                        continue

                    # If a final segment for this same utterance arrived while decoding an interim,
                    # skip emitting the superseded interim result.
                    if not u.is_final:
                        with self._interim_lock:
                            if u.utterance_id in self._finalized_ids:
                                continue

                    roman = romanize(text, lang)
                    english = ""
                    if self.translator and self.output_mode in ("translate", "all"):
                        if lang == "en":
                            english = text
                        elif u.is_final or self.tname == "offline":
                            try:
                                english = self.translator.translate(text, lang)
                            except Exception as e:
                                english = f"(translation error: {e})"

                    entry = TranscriptEntry(
                        id=u.utterance_id,
                        timestamp=u.started,
                        source=u.source,
                        lang=lang,
                        text=text,
                        roman=roman,
                        translation=english if english else None,
                        is_final=u.is_final,
                    )

                    if u.is_final:
                        formatted = format_entry_text(entry, self.output_mode)
                        f.write(formatted)
                        f.flush()

                    if self.on_entry:
                        self.on_entry(entry)
                finally:
                    if from_fifo:
                        self.q.task_done()

    def set_channel_enabled(self, source: str, enabled: bool) -> None:
        """Dynamically enable or disable capture for 'ME' or 'OTHERS'."""
        if source == "ME":
            self.enable_mic = enabled
        elif source == "OTHERS":
            self.enable_speaker = enabled

        if not enabled:
            with self._interim_lock:
                self._latest_interim.pop(source, None)

        with self._device_lock:
            found = False
            for c in self.captures:
                if c.segmenter.source == source:
                    c.set_enabled(enabled)
                    found = True
            # Channel was disabled when the stream was (re)opened: open it now
            if enabled and not found and self.p is not None and not self.stop_event.is_set():
                try:
                    self._open_capture(source)
                except Exception as e:
                    print(f"[Transcribbler] Failed to open {source} device: {e}", file=sys.stderr)

    def stop(self) -> None:
        """Stop audio streams, drain queue, and shut down cleanly."""
        # Signal stop first so a concurrent device reload won't reopen any streams
        self.stop_event.set()
        with self._device_lock:
            self._close_captures()

        with self._interim_lock:
            self._latest_interim.clear()

        self._work_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5.0)
            self.worker_thread = None

        with self._device_lock:
            if self.p:
                try:
                    self.p.terminate()
                except Exception:
                    pass
                self.p = None
