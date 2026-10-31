"""Reusable UI components and formatting helpers."""
from __future__ import annotations

import tkinter as tk
from typing import Optional

from transcribbler.core.events import TranscriptEntry
from transcribbler.ui.styles import FONT_FAMILY, TOOLTIP_BG, TOOLTIP_FG


class Tooltip:
    """Lightweight hover tooltip for any Tk/CustomTkinter widget.

    Shows a borderless, topmost popup near the pointer after `delay_ms` of hovering and
    hides it on leave or click. `text` can be changed at runtime.
    """

    def __init__(self, widget: tk.Misc, text: str, delay_ms: int = 400, wraplength: int = 320):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.wraplength = wraplength
        self._after_id: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_pointerx() + 12
        y = self.widget.winfo_pointery() + 18

        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        label = tk.Label(
            tip, text=self.text, justify="left",
            bg=TOOLTIP_BG, fg=TOOLTIP_FG, font=(FONT_FAMILY, 10),
            relief="solid", borderwidth=1, padx=8, pady=4, wraplength=self.wraplength,
        )
        label.pack()

        # Keep the tooltip on-screen (status bar sits at the bottom-right of the window)
        tip.update_idletasks()
        w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
        sw, sh = tip.winfo_screenwidth(), tip.winfo_screenheight()
        if x + w > sw:
            x = sw - w - 4
        if y + h > sh:
            y = self.widget.winfo_pointery() - h - 10
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


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
