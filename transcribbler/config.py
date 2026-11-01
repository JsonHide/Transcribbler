"""Global constants and configuration settings for Transcribbler."""
import os
from pathlib import Path

TARGET_SR = 16000
FRAME_MS = 30
FRAME_SAMPLES = TARGET_SR * FRAME_MS // 1000  # 480 samples @ 16 kHz

MODELS_ROOT = Path("models")
SENSE_VOICE_DIR = MODELS_ROOT / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
MODEL_DIR = SENSE_VOICE_DIR  # Backward-compatible alias
PARAKEET_EN_DIR = MODELS_ROOT / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
MOONSHINE_EN_DIR = MODELS_ROOT / "sherpa-onnx-moonshine-base-en-int8"
DEFAULT_EN_ENGINE = os.environ.get("TRANSCRIBBLER_EN_ENGINE", "auto").strip().lower()

TRANSCRIPTS_DIR = Path("transcripts")
YUE_CHARS = set("嘅咗哋唔係嚟啲冇喺嗰咁啱睇揾")
