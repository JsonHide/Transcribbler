"""Unit tests for transcript flush-on-stop/disable and English translation formatting."""
from __future__ import annotations

import queue
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from transcribbler.config import FRAME_SAMPLES, TARGET_SR
from transcribbler.core.audio import Segmenter
from transcribbler.core.events import TranscriptEntry, Utterance
from transcribbler.core.session import TranscriptionSession


def _make_speech_frame(amplitude: int = 8000) -> np.ndarray:
    t = np.arange(FRAME_SAMPLES, dtype=np.float32) / TARGET_SR
    return (amplitude * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.int16)


class TestFlushOnStopAndDisable(unittest.TestCase):
    """Ensure in-progress speech is finalized and saved to disk on Stop or Disable."""

    def test_segmenter_flush_preserves_interim_utterance_id(self):
        q: queue.Queue[Utterance] = queue.Queue()
        finals: list[Utterance] = []
        interims: list[Utterance] = []

        seg = Segmenter(
            "ME",
            q,
            on_final=finals.append,
            on_interim=interims.append,
        )
        seg.vad = MagicMock()
        seg.vad.is_speech.return_value = True

        # Feed 1.5s (50 frames) to trigger one interim preview
        frame = _make_speech_frame()
        for _ in range(50):
            seg.feed(frame)

        self.assertEqual(len(interims), 1)
        self.assertEqual(len(finals), 0)

        # Flush simulates Stop or Disable mid-sentence
        seg.flush()
        self.assertEqual(len(finals), 1)
        self.assertTrue(finals[0].is_final)
        self.assertEqual(finals[0].utterance_id, interims[0].utterance_id)

    def test_session_stop_writes_flushed_utterance_to_transcript_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "transcript_test.txt"
            received: list[TranscriptEntry] = []

            session = TranscriptionSession(
                translator_choice="off",
                enable_mic=False,
                enable_speaker=False,
                output_path=out_path,
                on_entry=received.append,
            )
            session.rec = MagicMock()
            session.rec.run.return_value = ("Hello before stop", "en")

            # Fake capture whose close() flushes an in-progress utterance like Capture.close()
            seg = Segmenter("ME", session.q, on_final=session._submit_final)
            seg.vad = MagicMock()
            seg.vad.is_speech.return_value = True
            for _ in range(15):  # 450ms > min_ms (300ms)
                seg.feed(_make_speech_frame())

            fake_capture = MagicMock()
            fake_capture.close.side_effect = seg.flush
            session.captures = [fake_capture]

            session.worker_thread = threading.Thread(target=session._worker_loop, daemon=True)
            session.worker_thread.start()

            session.stop()

            self.assertEqual(len(received), 1)
            self.assertTrue(received[0].is_final)
            self.assertEqual(received[0].text, "Hello before stop")

            disk_text = out_path.read_text(encoding="utf-8")
            self.assertIn("Hello before stop", disk_text)


class TestEnglishTranslationOmission(unittest.TestCase):
    """Ensure English sentences do not emit duplicate EN: lines when translation is on."""

    def _run_worker_once(self, output_mode: str, text: str, lang: str, translated: str = "Translated"):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "transcript_test.txt"
            received: list[TranscriptEntry] = []

            session = TranscriptionSession(
                translator_choice="off",
                output_mode=output_mode,
                enable_mic=False,
                enable_speaker=False,
                output_path=out_path,
                on_entry=received.append,
            )
            session.translator = MagicMock()
            session.translator.translate.return_value = translated
            session.tname = "offline"
            session.rec = MagicMock()
            session.rec.run.return_value = (text, lang)

            session.worker_thread = threading.Thread(target=session._worker_loop, daemon=True)
            session.worker_thread.start()

            session._submit_final(
                Utterance(
                    source="OTHERS",
                    audio=np.zeros(FRAME_SAMPLES, dtype=np.float32),
                    started=datetime(2026, 1, 1, 12, 0, 0),
                    is_final=True,
                )
            )
            session.stop()

            return received, out_path.read_text(encoding="utf-8"), session.translator

    def test_english_omits_duplicate_en_line_in_all_mode(self):
        received, disk_text, translator = self._run_worker_once("all", "Hello everyone", "en")
        self.assertEqual(len(received), 1)
        self.assertIsNone(received[0].translation)
        self.assertIn("Text:     Hello everyone", disk_text)
        self.assertNotIn("EN:", disk_text)
        translator.translate.assert_not_called()

    def test_english_kept_in_translate_only_mode(self):
        received, disk_text, translator = self._run_worker_once("translate", "Hello everyone", "en")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].translation, "Hello everyone")
        self.assertIn("EN:       Hello everyone", disk_text)
        translator.translate.assert_not_called()

    def test_cantonese_still_translated_in_all_mode(self):
        received, disk_text, translator = self._run_worker_once(
            "all", "唔該大家", "yue", translated="Please everyone"
        )
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].translation, "Please everyone")
        self.assertIn("EN:       Please everyone", disk_text)
        translator.translate.assert_called_once_with("唔該大家", "yue")


if __name__ == "__main__":
    unittest.main()
