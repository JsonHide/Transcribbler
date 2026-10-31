"""Event and data definitions for audio capture and speech recognition."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid
import numpy as np


@dataclass
class Utterance:
    source: str            # "ME" or "OTHERS"
    audio: np.ndarray      # float32, 16 kHz mono normalized [-1.0, 1.0]
    started: datetime
    utterance_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    is_final: bool = True


@dataclass
class TranscriptEntry:
    id: str
    timestamp: datetime
    source: str            # "ME" or "OTHERS"
    lang: str              # "en", "zh", "yue"
    text: str
    roman: Optional[str]
    translation: Optional[str]
    is_final: bool = True


@dataclass
class AudioStatusEvent:
    source: str            # "ME" or "OTHERS"
    is_capturing: bool
    is_speech: bool
    energy_level: float    # 0.0 to 1.0 for UI level meters
