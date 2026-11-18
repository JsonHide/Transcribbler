"""Unit and integration tests for CLI low-latency streaming and GUI preservation."""
from __future__ import annotations

import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from transcribbler.config import FRAME_MS, FRAME_SAMPLES, PARAKEET_EN_DIR, TARGET_SR
from transcribbler.core.audio import Segmenter
from transcribbler.core.events import Utterance
from transcribbler.core.session import TranscriptionSession


def _make_speech_frame(amplitude: int = 8000) -> np.ndarray:
    """Create a 30ms 16 kHz PCM16 frame with speech-like energy."""
    t = np.arange(FRAME_SAMPLES, dtype=np.float32) / TARGET_SR
    wave = amplitude * np.sin(2.0 * np.pi * 440.0 * t)
    return wave.astype(np.int16)


def _make_dip_frame(amplitude: int = 1200) -> np.ndarray:
    """Create a 30ms 16 kHz PCM16 frame representing a brief breath/clause dip."""
    t = np.arange(FRAME_SAMPLES, dtype=np.float32) / TARGET_SR
    wave = amplitude * np.sin(2.0 * np.pi * 440.0 * t)
    return wave.astype(np.int16)


def _make_silent_frame() -> np.ndarray:
    return np.zeros(FRAME_SAMPLES, dtype=np.int16)


class TestSegmenterDefaultsAndCliMode(unittest.TestCase):
    """Verify GUI defaults are preserved and CLI low-latency segmentation flushes in 2-3s."""

    def test_gui_defaults_unchanged(self):
        q: queue.Queue[Utterance] = queue.Queue()
        seg = Segmenter("ME", q)
        self.assertEqual(seg.silence_limit, 450 // FRAME_MS)
        self.assertEqual(seg.soft_max_frames, int(5.0 * 1000 // FRAME_MS))
        self.assertEqual(seg.soft_silence_limit, 150 // FRAME_MS)
        self.assertAlmostEqual(seg.soft_silence_rms_ratio, 0.18)
        self.assertEqual(seg.max_frames, int(12.0 * 1000 // FRAME_MS))

    def test_cli_soft_flush_on_energy_dip_during_continuous_speech(self):
        q: queue.Queue[Utterance] = queue.Queue()
        finals: list[Utterance] = []
        interims: list[Utterance] = []

        seg = Segmenter(
            "ME",
            q,
            on_final=finals.append,
            on_interim=None,
            silence_ms=360,
            soft_max_seconds=2.2,
            soft_silence_ms=90,
            soft_silence_rms_ratio=0.25,
            max_seconds=3.5,
        )
        # Mock VAD to always return True (continuous speech with hangover)
        seg.vad = MagicMock()
        seg.vad.is_speech.return_value = True

        speech_frame = _make_speech_frame(8000)
        dip_frame = _make_dip_frame(1200)  # ~15% of 8000 < 25% ratio

        # Feed 2.25s of continuous speech (75 frames * 30ms = 2250ms)
        for _ in range(75):
            seg.feed(speech_frame)
        self.assertEqual(len(finals), 0)

        # Feed 3 frames (90ms) of energy dip while VAD still reports True
        for _ in range(3):
            seg.feed(dip_frame)

        self.assertEqual(len(finals), 1)
        self.assertEqual(len(interims), 0)
        self.assertTrue(finals[0].is_final)
        duration_s = len(finals[0].audio) / TARGET_SR
        self.assertGreaterEqual(duration_s, 2.0)
        self.assertLessEqual(duration_s, 2.6)

    def test_cli_hard_flush_at_max_seconds_without_dip(self):
        q: queue.Queue[Utterance] = queue.Queue()
        finals: list[Utterance] = []

        seg = Segmenter(
            "OTHERS",
            q,
            on_final=finals.append,
            on_interim=None,
            silence_ms=360,
            soft_max_seconds=2.2,
            soft_silence_ms=90,
            soft_silence_rms_ratio=0.25,
            max_seconds=3.5,
        )
        seg.vad = MagicMock()
        seg.vad.is_speech.return_value = True

        speech_frame = _make_speech_frame(8000)
        # Feed 3.6s (120 frames) of steady speech with zero energy dips
        for _ in range(120):
            seg.feed(speech_frame)

        self.assertEqual(len(finals), 1)
        duration_s = len(finals[0].audio) / TARGET_SR
        self.assertLessEqual(duration_s, 3.5)

    def test_cli_silence_flush(self):
        q: queue.Queue[Utterance] = queue.Queue()
        finals: list[Utterance] = []

        seg = Segmenter(
            "ME",
            q,
            on_final=finals.append,
            on_interim=None,
            silence_ms=360,
            soft_max_seconds=2.2,
            soft_silence_ms=90,
            soft_silence_rms_ratio=0.25,
            max_seconds=3.5,
        )
        seg.vad = MagicMock()

        seg.vad.is_speech.return_value = True
        for _ in range(20):  # 600ms speech
            seg.feed(_make_speech_frame(8000))
        self.assertEqual(len(finals), 0)

        seg.vad.is_speech.return_value = False
        for _ in range(12):  # 360ms silence (12 * 30ms)
            seg.feed(_make_silent_frame())
        self.assertEqual(len(finals), 1)


class TestSessionAndCliWiring(unittest.TestCase):
    """Verify TranscriptionSession preserves GUI interims while CLI disables them."""

    @patch("transcribbler.core.session.Capture")
    @patch("transcribbler.core.session.Segmenter")
    def test_session_gui_default_enables_interim_and_default_segmenter(
        self, mock_seg_cls, mock_capture_cls
    ):
        session = TranscriptionSession(translator_choice="off", enable_speaker=False)
        session.p = MagicMock()
        session.p.get_default_input_device_info.return_value = {
            "index": 0,
            "name": "Mock Mic",
            "maxInputChannels": 1,
            "defaultSampleRate": 16000,
        }

        session._open_capture("ME")

        mock_seg_cls.assert_called_once()
        _, kwargs = mock_seg_cls.call_args
        self.assertEqual(kwargs["on_interim"], session._submit_interim)
        self.assertNotIn("soft_max_seconds", kwargs)
        self.assertNotIn("max_seconds", kwargs)
        self.assertNotIn("silence_ms", kwargs)

    @patch("transcribbler.core.session.Capture")
    @patch("transcribbler.core.session.Segmenter")
    def test_session_cli_disables_interim_and_forwards_segmenter_kwargs(
        self, mock_seg_cls, mock_capture_cls
    ):
        cli_kwargs = {
            "silence_ms": 360,
            "soft_max_seconds": 2.2,
            "soft_silence_ms": 90,
            "soft_silence_rms_ratio": 0.25,
            "max_seconds": 3.5,
        }
        session = TranscriptionSession(
            translator_choice="off",
            enable_speaker=False,
            enable_interim=False,
            segmenter_kwargs=cli_kwargs,
        )
        session.p = MagicMock()
        session.p.get_default_input_device_info.return_value = {
            "index": 0,
            "name": "Mock Mic",
            "maxInputChannels": 1,
            "defaultSampleRate": 16000,
        }

        session._open_capture("ME")

        mock_seg_cls.assert_called_once()
        _, kwargs = mock_seg_cls.call_args
        self.assertIsNone(kwargs["on_interim"])
        self.assertEqual(kwargs["silence_ms"], 360)
        self.assertEqual(kwargs["soft_max_seconds"], 2.2)
        self.assertEqual(kwargs["soft_silence_ms"], 90)
        self.assertEqual(kwargs["soft_silence_rms_ratio"], 0.25)
        self.assertEqual(kwargs["max_seconds"], 3.5)

    @patch("transcribbler.cli.TranscriptionSession")
    def test_run_cli_passes_low_latency_options(self, mock_session_cls):
        from transcribbler.cli import run_cli

        mock_session = MagicMock()
        mock_session.stop_event.is_set.return_value = True
        mock_session.engine_name = "Parakeet-TDT-0.6B-v2 (int8)"
        mock_session.tname = "off"
        mock_session.out_path = Path("transcripts/test.txt")
        mock_session_cls.return_value = mock_session

        with patch.object(sys, "argv", ["main.py", "--translator", "off", "--language", "en"]):
            run_cli()

        mock_session_cls.assert_called_once()
        _, kwargs = mock_session_cls.call_args
        self.assertFalse(kwargs["enable_interim"])
        self.assertEqual(
            kwargs["segmenter_kwargs"],
            {
                "silence_ms": 360,
                "soft_max_seconds": 2.2,
                "soft_silence_ms": 90,
                "soft_silence_rms_ratio": 0.25,
                "max_seconds": 3.5,
            },
        )


class TestParakeetModelSmoke(unittest.TestCase):
    """Smoke test Parakeet-TDT recognition if the local model is installed."""

    def test_parakeet_test_wav_recognition(self):
        wav_path = PARAKEET_EN_DIR / "test_wavs" / "0.wav"
        if not wav_path.is_file():
            self.skipTest("Parakeet test_wavs/0.wav not present")

        import wave
        from transcribbler.core.engine import Recognizer

        with wave.open(str(wav_path), "rb") as wf:
            sr = wf.getframerate()
            pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
            if wf.getnchannels() > 1:
                pcm = pcm.reshape(-1, wf.getnchannels()).mean(axis=1).astype(np.int16)
            audio = pcm.astype(np.float32) / 32768.0
            self.assertEqual(sr, TARGET_SR)

        rec = Recognizer(language="en", threads=4, en_engine="parakeet")
        text, lang = rec.run(audio)
        self.assertEqual(lang, "en")
        self.assertTrue(len(text.strip()) > 0)


if __name__ == "__main__":
    unittest.main()
