"""Unit tests for Cantonese Traditional Chinese (s2hk + phrase fixes), CLI flag, and session wiring."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from transcribbler.core.engine import Recognizer, romanize, to_traditional_hk
from transcribbler.core.session import TranscriptionSession


def _make_mock_recognizer(raw_text: str, lang_attr: str, yue_script: str = "traditional") -> Recognizer:
    """Create a Recognizer instance with a mocked sherpa-onnx backend (no model files required)."""
    rec = object.__new__(Recognizer)
    rec.language = "auto"
    rec.threads = 1
    rec.en_engine = "auto"
    rec.yue_script = yue_script
    rec.forced = None
    rec.engine_type = "sense_voice"
    rec.engine_name = "SenseVoice-Small (int8)"

    stream = MagicMock()
    stream.result.text = raw_text
    stream.result.lang = lang_attr

    backend = MagicMock()
    backend.create_stream.return_value = stream
    rec.rec = backend
    return rec


class TestCantoneseTraditionalConversion(unittest.TestCase):
    """Verify s2hk conversion, Hong Kong Cantonese phrase fixes, and Jyutping completeness."""

    def test_cantonese_samples_and_phrase_fixes(self):
        cases = [
            (
                "个人竟然代表咗咁多嘢，系咪咁，你点都要。",
                "個人竟然代表咗咁多嘢，係咪咁，你點都要。",
            ),
            (
                "翻去翻嚟咪就会买买 bad胎后。",
                "返去返嚟咪就會買買 bad胎後。",
            ),
            (
                "睇下点样收到金融系统嘅危机。",
                "睇下點樣收到金融系統嘅危機。",
            ),
            (
                "礼拜一定上礼拜你做都系咁讲啊。",
                "禮拜一定上禮拜你做都係咁講啊。",
            ),
            (
                "阿黄小姐就系佢真系。",
                "阿黃小姐就係佢真係。",
            ),
            (
                "受过啲个特务训练咁样。",
                "受過啲個特務訓練咁樣。",
            ),
            (
                "系唔系咁，定系唔系？",
                "係唔係咁，定係唔係？",
            ),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(to_traditional_hk(raw), expected)

    def test_standard_words_with_xi_not_corrupted(self):
        self.assertEqual(to_traditional_hk("金融系统同埋国际关系"), "金融系統同埋國際關係")
        self.assertEqual(to_traditional_hk("翻译呢份文件"), "翻譯呢份文件")

    def test_jyutping_complete_after_traditional_conversion(self):
        converted = to_traditional_hk("受过啲个特务训练咁样。")
        self.assertEqual(converted, "受過啲個特務訓練咁樣。")
        jp = romanize(converted, "yue")
        self.assertEqual(jp, "sau6 gwo3 di1 go3 dak6 mou6 fan3 lin6 gam3 joeng6")


class TestRecognizerAndSessionYueScript(unittest.TestCase):
    """Verify Recognizer.run, TranscriptionSession.set_yue_script, and CLI --yue-script wiring."""

    def test_recognizer_converts_yue_in_traditional_mode(self):
        rec = _make_mock_recognizer("<|yue|>睇下点样收到金融系统嘅危机。", "<|yue|>", yue_script="traditional")
        text, lang = rec.run(np.zeros(480, dtype=np.float32))
        self.assertEqual(lang, "yue")
        self.assertEqual(text, "睇下點樣收到金融系統嘅危機。")

    def test_recognizer_keeps_simplified_when_configured(self):
        rec = _make_mock_recognizer("<|yue|>睇下点样收到金融系统嘅危机。", "<|yue|>", yue_script="simplified")
        text, lang = rec.run(np.zeros(480, dtype=np.float32))
        self.assertEqual(lang, "yue")
        self.assertEqual(text, "睇下点样收到金融系统嘅危机。")

    def test_recognizer_leaves_mandarin_unchanged(self):
        rec = _make_mock_recognizer("<|zh|>金融系统的危机", "<|zh|>", yue_script="traditional")
        text, lang = rec.run(np.zeros(480, dtype=np.float32))
        self.assertEqual(lang, "zh")
        self.assertEqual(text, "金融系统的危机")

    def test_session_set_yue_script_updates_live_recognizer(self):
        session = TranscriptionSession(translator_choice="off", enable_mic=False, enable_speaker=False)
        session.rec = _make_mock_recognizer("<|yue|>都系咁讲啊。", "<|yue|>", yue_script="traditional")

        text_trad, _ = session.rec.run(np.zeros(480, dtype=np.float32))
        self.assertEqual(text_trad, "都係咁講啊。")

        session.set_yue_script("simplified")
        self.assertEqual(session.yue_script, "simplified")
        self.assertEqual(session.rec.yue_script, "simplified")

        text_simp, _ = session.rec.run(np.zeros(480, dtype=np.float32))
        self.assertEqual(text_simp, "都系咁讲啊。")

    @patch("transcribbler.cli.TranscriptionSession")
    def test_cli_yue_script_flag_default_and_override(self, mock_session_cls):
        from transcribbler.cli import run_cli

        mock_session = MagicMock()
        mock_session.stop_event.is_set.return_value = True
        mock_session.engine_name = "SenseVoice-Small (int8)"
        mock_session.tname = "off"
        mock_session.out_path = Path("transcripts/test.txt")
        mock_session_cls.return_value = mock_session

        with patch.object(sys, "argv", ["main.py", "--translator", "off"]):
            run_cli()
        self.assertEqual(mock_session_cls.call_args.kwargs["yue_script"], "traditional")

        mock_session_cls.reset_mock()
        with patch.object(sys, "argv", ["main.py", "--translator", "off", "--yue-script", "simplified"]):
            run_cli()
        self.assertEqual(mock_session_cls.call_args.kwargs["yue_script"], "simplified")


if __name__ == "__main__":
    unittest.main()
