"""Global constants and configuration settings for Transcribbler."""
import os
from pathlib import Path

from transcribbler import __version__

APP_VERSION = f"v{__version__}"
APP_TITLE = f"Transcribbler – Real-Time ASR & Translation – {APP_VERSION}"

TARGET_SR = 16000
FRAME_MS = 30
FRAME_SAMPLES = TARGET_SR * FRAME_MS // 1000  # 480 samples @ 16 kHz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_ROOT = PROJECT_ROOT / "models"
SENSE_VOICE_DIR = MODELS_ROOT / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
MODEL_DIR = SENSE_VOICE_DIR  # Backward-compatible alias
PARAKEET_EN_DIR = MODELS_ROOT / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
MOONSHINE_EN_DIR = MODELS_ROOT / "sherpa-onnx-moonshine-base-en-int8"
DEFAULT_EN_ENGINE = os.environ.get("TRANSCRIBBLER_EN_ENGINE", "auto").strip().lower()

TRANSCRIPTS_DIR = PROJECT_ROOT / "transcripts"
YUE_CHARS = set("嘅咗哋唔係嚟啲冇喺嗰咁啱睇揾")
