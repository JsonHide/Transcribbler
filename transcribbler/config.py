"""Global constants and configuration settings for Transcribbler."""
from pathlib import Path

TARGET_SR = 16000
FRAME_MS = 30
FRAME_SAMPLES = TARGET_SR * FRAME_MS // 1000  # 480 samples @ 16 kHz
MODEL_DIR = Path("models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17")
TRANSCRIPTS_DIR = Path("transcripts")
YUE_CHARS = set("嘅咗哋唔係嚟啲冇喺嗰咁啱睇揾")
