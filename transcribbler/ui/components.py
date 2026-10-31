"""Reusable UI components and formatting helpers."""
from __future__ import annotations

from transcribbler.core.events import TranscriptEntry


def format_entry_block(entry: TranscriptEntry, include_source: bool = False) -> str:
    """Format a TranscriptEntry as a multi-line text block with language-specific tags."""
    ts = entry.timestamp.strftime("%H:%M:%S")
    live_badge = "" if entry.is_final else " ⏳"
    ellipsis = "" if entry.is_final else " …"

    if include_source:
        tag = "🎤 ME" if entry.source == "ME" else "🔊 OTHERS"
        header = f"[{ts}] {tag} ({entry.lang}){live_badge}"
    else:
        header = f"[{ts}] ({entry.lang}){live_badge}"

    lines = [header, f"  Text:     {entry.text}{ellipsis}"]

    if entry.roman:
        roman_label = "Pinyin" if entry.lang == "zh" else "Jyutping"
        lines.append(f"  {roman_label}: {entry.roman}")

    if entry.translation:
        lines.append(f"  EN:       {entry.translation}")

    return "\n".join(lines) + "\n\n"
