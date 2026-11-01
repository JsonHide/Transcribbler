"""Speech recognition (SenseVoice), romanization, and translation backends."""
from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np
import pycantonese
from pypinyin import Style, lazy_pinyin
import sherpa_onnx

from transcribbler.config import (
    DEFAULT_EN_ENGINE,
    MOONSHINE_EN_DIR,
    PARAKEET_EN_DIR,
    SENSE_VOICE_DIR,
    TARGET_SR,
    YUE_CHARS,
)

TAG_RE = re.compile(r"<\|[^|]*\|>")


def _pick_file(directory: Path, *candidates: str) -> Optional[Path]:
    """Return the first candidate filename that exists inside directory."""
    for name in candidates:
        p = directory / name
        if p.is_file():
            return p
    return None


def guess_lang(text: str) -> str:
    """Fallback heuristic when language metadata is absent."""
    if re.search(r"[\u4e00-\u9fff]", text):
        return "yue" if any(c in YUE_CHARS for c in text) else "zh"
    return "en"


class Recognizer:
    """Language-driven dual-engine ASR selector via sherpa-onnx (CPU, INT8).

    - language == 'en':
        1. Primary: sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8 (from_transducer, nemo_transducer)
        2. Fallback: sherpa-onnx-moonshine-base-en-int8 (from_moonshine)
    - language == 'auto' (or 'zh' / 'yue'):
        - sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17 (from_sense_voice, use_itn=True)
    """

    def __init__(self, language: str = "auto", threads: int = 4, en_engine: str = "auto"):
        self.language = language
        self.threads = threads
        self.en_engine = (en_engine if en_engine and en_engine != "auto" else DEFAULT_EN_ENGINE) or "auto"
        self.forced = None if language == "auto" else language
        self.engine_type = "sense_voice"
        self.engine_name = "SenseVoice-Small (int8)"
        self.rec: Any = None

        if language == "en":
            loaders = (
                (self._try_load_moonshine, self._try_load_parakeet)
                if self.en_engine == "moonshine"
                else (self._try_load_parakeet, self._try_load_moonshine)
            )
            loaded = any(loader(threads) for loader in loaders)
            if not loaded:
                raise RuntimeError(
                    f"English ASR model files missing at:\n"
                    f"  - Primary (Parakeet): {PARAKEET_EN_DIR}\n"
                    f"  - Fallback (Moonshine): {MOONSHINE_EN_DIR}\n"
                    "Please download sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8 (or "
                    "sherpa-onnx-moonshine-base-en-int8) into models/.\n"
                    "See Section 6.3 in TRANSCRIBBLER_IMPLEMENTATION_v3.md for instructions."
                )
        else:
            self._load_sense_voice(language, threads)

    def _try_load_parakeet(self, threads: int) -> bool:
        if not PARAKEET_EN_DIR.is_dir():
            return False
        encoder = _pick_file(PARAKEET_EN_DIR, "encoder.int8.onnx", "encoder.onnx")
        decoder = _pick_file(PARAKEET_EN_DIR, "decoder.int8.onnx", "decoder.onnx")
        joiner = _pick_file(PARAKEET_EN_DIR, "joiner.int8.onnx", "joiner.onnx")
        tokens = _pick_file(PARAKEET_EN_DIR, "tokens.txt")
        if not (encoder and decoder and joiner and tokens):
            return False

        self.rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(encoder),
            decoder=str(decoder),
            joiner=str(joiner),
            tokens=str(tokens),
            num_threads=threads,
            provider="cpu",
            model_type="nemo_transducer",
        )
        self.engine_type = "parakeet"
        self.engine_name = "Parakeet-TDT-0.6B-v2 (int8)"
        return True

    def _try_load_moonshine(self, threads: int) -> bool:
        if not MOONSHINE_EN_DIR.is_dir():
            return False
        preprocess = _pick_file(MOONSHINE_EN_DIR, "preprocess.onnx")
        encode = _pick_file(MOONSHINE_EN_DIR, "encode.int8.onnx", "encode.onnx")
        uncached = _pick_file(MOONSHINE_EN_DIR, "uncached_decode.int8.onnx", "uncached_decode.onnx")
        cached = _pick_file(MOONSHINE_EN_DIR, "cached_decode.int8.onnx", "cached_decode.onnx")
        tokens = _pick_file(MOONSHINE_EN_DIR, "tokens.txt")
        if not (preprocess and encode and uncached and cached and tokens):
            return False

        self.rec = sherpa_onnx.OfflineRecognizer.from_moonshine(
            preprocessor=str(preprocess),
            encoder=str(encode),
            uncached_decoder=str(uncached),
            cached_decoder=str(cached),
            tokens=str(tokens),
            num_threads=threads,
            provider="cpu",
        )
        self.engine_type = "moonshine"
        self.engine_name = "Moonshine-Base-EN (int8)"
        return True

    def _load_sense_voice(self, language: str, threads: int) -> None:
        model_file = _pick_file(SENSE_VOICE_DIR, "model.int8.onnx", "model.onnx")
        tokens_file = _pick_file(SENSE_VOICE_DIR, "tokens.txt")

        if not (model_file and tokens_file):
            raise RuntimeError(
                f"Model files missing at {SENSE_VOICE_DIR}.\n"
                "Please download the SenseVoice INT8 model package before running.\n"
                "See Section 6.3 in TRANSCRIBBLER_IMPLEMENTATION_v3.md for instructions."
            )

        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_file),
            tokens=str(tokens_file),
            num_threads=threads,
            use_itn=True,
            language=language,
            provider="cpu",
        )
        self.engine_type = "sense_voice"
        self.engine_name = "SenseVoice-Small (int8)"

    def run(self, audio: np.ndarray) -> Tuple[str, Optional[str]]:
        """Recognize an utterance. Returns (text, lang) or ("", None) if empty."""
        stream = self.rec.create_stream()
        stream.accept_waveform(TARGET_SR, audio)
        self.rec.decode_stream(stream)
        res = stream.result

        raw_text = getattr(res, "text", "") or ""

        if self.engine_type in ("parakeet", "moonshine"):
            text = TAG_RE.sub("", raw_text).strip()
            if not text:
                return "", None
            return text, "en"

        # SenseVoice: extract language tag BEFORE stripping control tokens
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


def romanize(text: str, lang: str) -> Optional[str]:
    """Generate romanization: Mandarin → Pinyin, Cantonese → Jyutping."""
    if lang == "zh":
        return " ".join(lazy_pinyin(text, style=Style.TONE))
    if lang == "yue":
        tokens = [j for _, j in pycantonese.characters_to_jyutping(text) if j]
        return " ".join(tokens) if tokens else None
    return None


class OfflineTranslator:
    """Argos Translate (zh -> en). Converts Traditional to Simplified first via OpenCC."""

    def __init__(self):
        import argostranslate.translate as t
        from opencc import OpenCC

        installed = t.get_installed_languages()
        codes = {l.code for l in installed}
        if not {"zh", "en"} <= codes:
            raise RuntimeError(
                "Offline pack missing. Run: python main.py --cli --install-offline-pack"
            )

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


BACKENDS = {
    "offline": OfflineTranslator,
    "azure": AzureTranslator,
    "google": GoogleTranslator,
}


def install_offline_pack() -> None:
    """Download and install Argos Translate zh -> en language pack."""
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


def make_translator(choice: str) -> Tuple[Optional[Any], str]:
    """Create a translator instance from the user's choice string."""
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

    if choice == "off" or not choice:
        return None, "off"
    if choice not in BACKENDS:
        return None, "off"
    return BACKENDS[choice](), choice
