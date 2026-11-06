"""Interactive CustomTkinter GUI for Transcribbler."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from transcribbler.core.audio import get_audio_devices, get_device_topology_signature
from transcribbler.core.events import TranscriptEntry
from transcribbler.core.session import TranscriptionSession
from transcribbler.ui.components import Tooltip, format_entry_block
from transcribbler.ui.styles import (
    BG_SECONDARY,
    BTN_ACCENT_FG,
    BTN_ACCENT_HOVER,
    BTN_BUSY_FG,
    BTN_NEUTRAL_FG,
    BTN_NEUTRAL_HOVER,
    BTN_START_FG,
    BTN_START_HOVER,
    BTN_STOP_FG,
    BTN_STOP_HOVER,
    CLUSTER_BG,
    CLUSTER_BORDER,
    CLUSTER_HOVER_BG,
    FONT_FAMILY,
    FONT_SIZE_DEFAULT,
    FONT_SIZE_MAX,
    FONT_SIZE_MIN,
    ICON_DANGER_HOVER_FG,
    ICON_FG,
    ICON_HOVER_FG,
    LED_ACTIVE,
    LED_IDLE,
    MIC_BTN_DISABLE_FG,
    MIC_BTN_DISABLE_HOVER,
    MIC_BTN_ENABLE_FG,
    MIC_BTN_ENABLE_HOVER,
    MIC_HEADER_COLOR,
    MONO_FONT_FAMILY,
    SPK_BTN_DISABLE_FG,
    SPK_BTN_DISABLE_HOVER,
    SPK_BTN_ENABLE_FG,
    SPK_BTN_ENABLE_HOVER,
    SPK_HEADER_COLOR,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    VIEW_ACTIVE_BG,
    VIEW_ACTIVE_FG,
    VIEW_INACTIVE_FG,
    VIEW_PILL_BG,
    VIEW_PILL_BORDER,
)
import pyaudiowpatch as pyaudio

RESCAN_TOOLTIP = "Rescan audio devices — detect newly plugged-in USB / Bluetooth headsets"
LANG_TOOLTIP = (
    "auto: SenseVoice-Small (Multilingual EN / Cantonese / Mandarin + Romanization)\n"
    "en: Parakeet-TDT-0.6B-v2 / Moonshine (English Meetings & Podcasts)"
)
EN_ENGINE_TOOLTIP = (
    "Only used when Lang = en\n"
    "auto: Parakeet-TDT-0.6B-v2, falls back to Moonshine if missing\n"
    "parakeet: Parakeet-TDT-0.6B-v2 (higher accuracy)\n"
    "moonshine: Moonshine-Base (lighter / faster)"
)


class TranscribblerApp(ctk.CTk):
    """Main Transcribbler desktop GUI application."""

    def __init__(self):
        super().__init__()
        self.title("Transcribbler – Real-Time ASR & Translation")
        self.geometry("1180x720")
        self.minsize(800, 500)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.session: Optional[TranscriptionSession] = None
        self.event_queue: queue.Queue[TranscriptEntry] = queue.Queue()
        self.activity_queue: queue.Queue[tuple[str, bool, float]] = queue.Queue()
        self.device_queue: queue.Queue[tuple] = queue.Queue()
        self._refreshing = False

        self.entries: list[TranscriptEntry] = []
        self._entry_index_by_id: dict[str, int] = {}
        self._mics_map: dict[str, int] = {}
        self._spks_map: dict[str, int] = {}

        self.filter_mode = "all"        # "all", "me", "others"
        self.layout_mode = "dual"       # "dual", "unified"
        self.font_size = FONT_SIZE_DEFAULT
        self.is_running = False

        self.mic_enabled = True
        self.spk_enabled = True

        self._last_mic_speech = 0.0
        self._last_spk_speech = 0.0

        self._build_top_bar()
        self._build_content_area()
        self._build_status_bar()
        self._load_devices()
        self._watcher_stop = threading.Event()
        self.hotplug_queue: queue.Queue[bool] = queue.Queue()
        self._start_hotplug_watcher()

        self.after(100, self._process_events)

    def _build_top_bar(self):
        self.top_frame = ctk.CTkFrame(self, corner_radius=8, fg_color=BG_SECONDARY)
        self.top_frame.pack(fill="x", padx=12, pady=(12, 6))

        row1 = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        row1.pack(fill="x", padx=8, pady=(6, 6))

        # --- Left Cluster: Session CTA + Audio/View Group + Speech Pipeline Group ---
        self.start_btn = ctk.CTkButton(
            row1, text="▶ Start", width=86, height=32,
            fg_color=BTN_START_FG, hover_color=BTN_START_HOVER,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=self.toggle_session,
        )
        self.start_btn.pack(side="left", padx=(0, 8))

        # Audio & View Cluster (Filter + View Mode Switcher)
        self.audio_view_cluster = ctk.CTkFrame(
            row1, fg_color=CLUSTER_BG, border_color=CLUSTER_BORDER,
            border_width=1, corner_radius=6,
        )
        self.audio_view_cluster.pack(side="left", padx=(0, 8))

        self.filter_combo = ctk.CTkComboBox(
            self.audio_view_cluster,
            values=["All Sources", "Mic Only", "Speaker Only"],
            width=110, height=26,
            fg_color=CLUSTER_BG, button_color=CLUSTER_BG,
            button_hover_color=CLUSTER_HOVER_BG, border_width=0,
            command=self._on_filter_changed, state="readonly",
        )
        self.filter_combo.set("All Sources")
        self.filter_combo.pack(side="left", padx=(4, 2), pady=3)
        self.filter_tooltip = Tooltip(self.filter_combo, "Filter audio input channel")

        av_sep = ctk.CTkFrame(self.audio_view_cluster, width=1, height=20, fg_color=CLUSTER_BORDER)
        av_sep.pack(side="left", padx=(2, 2), pady=4)

        self.view_pill = ctk.CTkFrame(self.audio_view_cluster, fg_color="transparent")
        self.view_pill.pack(side="left", padx=(1, 3), pady=3)

        self.dual_seg = ctk.CTkFrame(
            self.view_pill, width=28, height=24, corner_radius=4, fg_color=VIEW_ACTIVE_BG,
        )
        self.dual_seg.pack(side="left", padx=(1, 1))
        self.dual_seg.pack_propagate(False)
        self.dual_canvas = tk.Canvas(
            self.dual_seg, width=16, height=14,
            bg=VIEW_ACTIVE_BG, highlightthickness=0, bd=0, cursor="hand2",
        )
        self.dual_canvas.place(relx=0.5, rely=0.5, anchor="center")

        self.uni_seg = ctk.CTkFrame(
            self.view_pill, width=28, height=24, corner_radius=4, fg_color=VIEW_PILL_BG,
        )
        self.uni_seg.pack(side="left", padx=(1, 1))
        self.uni_seg.pack_propagate(False)
        self.uni_canvas = tk.Canvas(
            self.uni_seg, width=16, height=14,
            bg=VIEW_PILL_BG, highlightthickness=0, bd=0, cursor="hand2",
        )
        self.uni_canvas.place(relx=0.5, rely=0.5, anchor="center")

        for w in (self.dual_seg, self.dual_canvas):
            w.bind("<Button-1>", lambda _e: self._on_layout_changed("Dual Column"))
        for w in (self.uni_seg, self.uni_canvas):
            w.bind("<Button-1>", lambda _e: self._on_layout_changed("Unified Timeline"))

        self.dual_tooltip = Tooltip(self.dual_canvas, "Split dual-column view (Mic & Speaker)")
        self.uni_tooltip = Tooltip(self.uni_canvas, "Single continuous stream layout")
        self._update_view_toggle()

        # Speech Pipeline Cluster (Lang | Model | Translate)
        self.pipeline_cluster = ctk.CTkFrame(
            row1, fg_color=CLUSTER_BG, border_color=CLUSTER_BORDER,
            border_width=1, corner_radius=6,
        )
        self.pipeline_cluster.pack(side="left", padx=(0, 6))

        mono_lbl_font = ctk.CTkFont(family=MONO_FONT_FAMILY, size=11)

        ctk.CTkLabel(
            self.pipeline_cluster, text="Lang:", font=mono_lbl_font, text_color=TEXT_SECONDARY,
        ).pack(side="left", padx=(8, 2), pady=3)
        self.lang_combo = ctk.CTkComboBox(
            self.pipeline_cluster,
            values=["auto", "en"],
            width=66, height=26,
            fg_color=CLUSTER_BG, button_color=CLUSTER_BG,
            button_hover_color=CLUSTER_HOVER_BG, border_width=0,
            command=self._on_lang_changed, state="readonly",
        )
        self.lang_combo.set("auto")
        self.lang_combo.pack(side="left", padx=(0, 4), pady=3)
        self.lang_tooltip = Tooltip(self.lang_combo, LANG_TOOLTIP)

        pipe_sep1 = ctk.CTkFrame(self.pipeline_cluster, width=1, height=20, fg_color=CLUSTER_BORDER)
        pipe_sep1.pack(side="left", padx=2, pady=4)

        self.en_engine_label = ctk.CTkLabel(
            self.pipeline_cluster, text="Model:", font=mono_lbl_font, text_color=TEXT_SECONDARY,
        )
        self.en_engine_label.pack(side="left", padx=(6, 2), pady=3)
        self.en_engine_combo = ctk.CTkComboBox(
            self.pipeline_cluster,
            values=["auto", "parakeet", "moonshine"],
            width=96, height=26,
            fg_color=CLUSTER_BG, button_color=CLUSTER_BG,
            button_hover_color=CLUSTER_HOVER_BG, border_width=0,
            state="disabled",
        )
        self.en_engine_combo.set("auto")
        self.en_engine_combo.pack(side="left", padx=(0, 4), pady=3)
        self.en_engine_tooltip = Tooltip(self.en_engine_combo, EN_ENGINE_TOOLTIP)

        pipe_sep2 = ctk.CTkFrame(self.pipeline_cluster, width=1, height=20, fg_color=CLUSTER_BORDER)
        pipe_sep2.pack(side="left", padx=2, pady=4)

        ctk.CTkLabel(
            self.pipeline_cluster, text="Translate:", font=mono_lbl_font, text_color=TEXT_SECONDARY,
        ).pack(side="left", padx=(6, 2), pady=3)
        self.trans_combo = ctk.CTkComboBox(
            self.pipeline_cluster,
            values=["off", "offline", "azure", "google"],
            width=80, height=26,
            fg_color=CLUSTER_BG, button_color=CLUSTER_BG,
            button_hover_color=CLUSTER_HOVER_BG, border_width=0,
            state="readonly",
        )
        self.trans_combo.set("off")
        self.trans_combo.pack(side="left", padx=(0, 6), pady=3)
        self.trans_tooltip = Tooltip(self.trans_combo, "Real-Time Translation Target")

        # --- Right Cluster: Compact Font Scaler + Document Utilities + Pin Toggle ---
        self.utility_cluster = ctk.CTkFrame(
            row1, fg_color=CLUSTER_BG, border_color=CLUSTER_BORDER,
            border_width=1, corner_radius=6,
        )
        self.utility_cluster.pack(side="right", padx=(4, 0))

        self.font_minus_btn = ctk.CTkButton(
            self.utility_cluster, text="A-", width=28, height=24,
            fg_color="transparent", hover_color=CLUSTER_HOVER_BG,
            text_color=ICON_FG, font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            command=self._font_decrease,
        )
        self.font_minus_btn.pack(side="left", padx=(4, 1), pady=3)
        self.font_minus_tooltip = Tooltip(self.font_minus_btn, "Decrease Font Size")

        self.font_label = ctk.CTkLabel(
            self.utility_cluster, text=f"{self.font_size}pt",
            font=mono_lbl_font, text_color=TEXT_SECONDARY, width=30,
        )
        self.font_label.pack(side="left", padx=1, pady=3)

        self.font_plus_btn = ctk.CTkButton(
            self.utility_cluster, text="A+", width=28, height=24,
            fg_color="transparent", hover_color=CLUSTER_HOVER_BG,
            text_color=ICON_FG, font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            command=self._font_increase,
        )
        self.font_plus_btn.pack(side="left", padx=(1, 3), pady=3)
        self.font_plus_tooltip = Tooltip(self.font_plus_btn, "Increase Font Size")

        util_sep1 = ctk.CTkFrame(self.utility_cluster, width=1, height=18, fg_color=CLUSTER_BORDER)
        util_sep1.pack(side="left", padx=2, pady=4)

        self.copy_btn, self.copy_canvas = self._create_icon_button(
            self.utility_cluster, self._draw_copy_icon, self._copy_transcripts,
            tooltip="Copy Transcript", hover_fg=ICON_HOVER_FG,
        )
        self.copy_btn.pack(side="left", padx=1, pady=3)

        self.save_btn, self.save_canvas = self._create_icon_button(
            self.utility_cluster, self._draw_save_icon, self._save_transcripts,
            tooltip="Save Transcript", hover_fg=ICON_HOVER_FG,
        )
        self.save_btn.pack(side="left", padx=1, pady=3)

        self.clear_btn, self.clear_canvas = self._create_icon_button(
            self.utility_cluster, self._draw_trash_icon, self._clear_transcripts,
            tooltip="Clear Session", hover_fg=ICON_DANGER_HOVER_FG,
        )
        self.clear_btn.pack(side="left", padx=1, pady=3)

        util_sep2 = ctk.CTkFrame(self.utility_cluster, width=1, height=18, fg_color=CLUSTER_BORDER)
        util_sep2.pack(side="left", padx=2, pady=4)

        self.topmost_var = ctk.BooleanVar(value=False)
        self.pin_btn = ctk.CTkFrame(
            self.utility_cluster, width=28, height=24, corner_radius=4, fg_color=CLUSTER_BG,
        )
        self.pin_btn.pack(side="left", padx=(1, 4), pady=3)
        self.pin_btn.pack_propagate(False)
        self.pin_canvas = tk.Canvas(
            self.pin_btn, width=16, height=16,
            bg=CLUSTER_BG, highlightthickness=0, bd=0, cursor="hand2",
        )
        self.pin_canvas.place(relx=0.5, rely=0.5, anchor="center")
        for w in (self.pin_btn, self.pin_canvas):
            w.bind("<Button-1>", lambda _e: self._toggle_pin())
            w.bind("<Enter>", lambda _e: self._set_pin_hover(True))
            w.bind("<Leave>", lambda _e: self._set_pin_hover(False))
        self.pin_tooltip = Tooltip(self.pin_canvas, "Always on Top")
        self._pin_hovered = False
        self._update_pin_button()

    def _create_icon_button(
        self,
        parent: ctk.CTkFrame,
        draw_fn,
        command,
        tooltip: str,
        hover_fg: str = ICON_HOVER_FG,
    ) -> tuple[ctk.CTkFrame, tk.Canvas]:
        """Build a 28x24 icon button using a crisp vector canvas inside a rounded CTkFrame."""
        btn = ctk.CTkFrame(parent, width=28, height=24, corner_radius=4, fg_color=CLUSTER_BG)
        btn.pack_propagate(False)
        canvas = tk.Canvas(
            btn, width=16, height=16, bg=CLUSTER_BG, highlightthickness=0, bd=0, cursor="hand2",
        )
        canvas.place(relx=0.5, rely=0.5, anchor="center")
        draw_fn(canvas, ICON_FG)

        def _on_enter(_e):
            btn.configure(fg_color=CLUSTER_HOVER_BG)
            canvas.configure(bg=CLUSTER_HOVER_BG)
            draw_fn(canvas, hover_fg)

        def _on_leave(_e):
            btn.configure(fg_color=CLUSTER_BG)
            canvas.configure(bg=CLUSTER_BG)
            draw_fn(canvas, ICON_FG)

        for w in (btn, canvas):
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)
            w.bind("<Button-1>", lambda _e: command())

        Tooltip(canvas, tooltip)
        return btn, canvas

    @staticmethod
    def _draw_copy_icon(canvas: tk.Canvas, color: str) -> None:
        canvas.delete("all")
        canvas.create_line(4, 11, 2, 11, 2, 2, 11, 2, 11, 4, fill=color, width=1.4)
        canvas.create_rectangle(5, 5, 14, 14, outline=color, width=1.4)

    @staticmethod
    def _draw_save_icon(canvas: tk.Canvas, color: str) -> None:
        canvas.delete("all")
        canvas.create_polygon(2, 2, 11, 2, 14, 5, 14, 14, 2, 14, outline=color, fill="", width=1.4)
        canvas.create_rectangle(5, 2, 10, 6, outline=color, width=1.2)
        canvas.create_rectangle(4, 9, 12, 14, outline=color, width=1.2)

    @staticmethod
    def _draw_trash_icon(canvas: tk.Canvas, color: str) -> None:
        canvas.delete("all")
        canvas.create_line(2, 4, 14, 4, fill=color, width=1.4)
        canvas.create_line(6, 2, 10, 2, fill=color, width=1.4)
        canvas.create_rectangle(4, 4, 12, 14, outline=color, width=1.4)
        canvas.create_line(6.5, 7, 6.5, 11.5, fill=color, width=1.2)
        canvas.create_line(9.5, 7, 9.5, 11.5, fill=color, width=1.2)

    def _build_content_area(self):
        self.body_frame = ctk.CTkFrame(self, corner_radius=8)
        self.body_frame.pack(fill="both", expand=True, padx=12, pady=6)

        self.dual_container = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.dual_container.pack(fill="both", expand=True)

        self.mic_frame = ctk.CTkFrame(self.dual_container)
        self.mic_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.mic_header = ctk.CTkFrame(self.mic_frame, height=38, fg_color=MIC_HEADER_COLOR)
        self.mic_header.pack(fill="x")
        self.mic_header.pack_propagate(False)
        self.mic_title = ctk.CTkLabel(
            self.mic_header, text="🎤 Microphone (ME)", font=ctk.CTkFont(weight="bold")
        )
        self.mic_title.pack(side="left", padx=10, pady=4)
        self.mic_toggle_btn = ctk.CTkButton(
            self.mic_header, text="Disable", width=68, height=24,
            fg_color=MIC_BTN_DISABLE_FG, hover_color=MIC_BTN_DISABLE_HOVER,
            border_color="#4dabf7", border_width=1,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_mic_channel,
        )
        self.mic_toggle_btn.pack(side="left", padx=6)
        self.mic_led = ctk.CTkLabel(self.mic_header, text=f"{LED_IDLE} Idle")
        self.mic_led.pack(side="right", padx=10)

        self.mic_textbox = ctk.CTkTextbox(
            self.mic_frame, font=(FONT_FAMILY, self.font_size), wrap="word",
        )
        self.mic_textbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.spk_frame = ctk.CTkFrame(self.dual_container)
        self.spk_frame.pack(side="right", fill="both", expand=True, padx=(4, 0))

        self.spk_header = ctk.CTkFrame(self.spk_frame, height=38, fg_color=SPK_HEADER_COLOR)
        self.spk_header.pack(fill="x")
        self.spk_header.pack_propagate(False)
        self.spk_title = ctk.CTkLabel(
            self.spk_header, text="🔊 Speaker / System (OTHERS)", font=ctk.CTkFont(weight="bold")
        )
        self.spk_title.pack(side="left", padx=10, pady=4)
        self.spk_toggle_btn = ctk.CTkButton(
            self.spk_header, text="Disable", width=68, height=24,
            fg_color=SPK_BTN_DISABLE_FG, hover_color=SPK_BTN_DISABLE_HOVER,
            border_color="#69db7c", border_width=1,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_spk_channel,
        )
        self.spk_toggle_btn.pack(side="left", padx=6)
        self.spk_led = ctk.CTkLabel(self.spk_header, text=f"{LED_IDLE} Idle")
        self.spk_led.pack(side="right", padx=10)

        self.spk_textbox = ctk.CTkTextbox(
            self.spk_frame, font=(FONT_FAMILY, self.font_size), wrap="word",
        )
        self.spk_textbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.unified_frame = ctk.CTkFrame(self.body_frame)
        self.unified_textbox = ctk.CTkTextbox(
            self.unified_frame, font=(FONT_FAMILY, self.font_size), wrap="word",
        )
        self.unified_textbox.pack(fill="both", expand=True, padx=6, pady=6)

    def _build_status_bar(self):
        self.status_bar = ctk.CTkFrame(self, height=46, corner_radius=6, fg_color=BG_SECONDARY)
        self.status_bar.pack(fill="x", padx=12, pady=(0, 8))
        self.status_bar.pack_propagate(False)

        # Right side: Always-visible audio device selectors & Rescan button
        self.device_bar_frame = ctk.CTkFrame(self.status_bar, fg_color="transparent")
        self.device_bar_frame.pack(side="right", fill="y", padx=(6, 6), pady=4)

        self.refresh_btn = ctk.CTkButton(
            self.device_bar_frame, text="⟳ Rescan", width=82, height=26,
            fg_color=BTN_ACCENT_FG, hover_color=BTN_ACCENT_HOVER,
            text_color="#ffffff", text_color_disabled="#ffffff",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=lambda: self._refresh_devices_async(reason="manual"),
        )
        self.refresh_btn.pack(side="right", padx=(4, 0), pady=5)
        self.refresh_tooltip = Tooltip(self.refresh_btn, RESCAN_TOOLTIP)

        self.spk_combo = ctk.CTkComboBox(
            self.device_bar_frame, values=["Default Loopback"],
            width=195, height=26,
            fg_color=CLUSTER_BG, border_color=CLUSTER_BORDER, border_width=1,
            button_color=CLUSTER_BG, button_hover_color=CLUSTER_HOVER_BG,
            state="readonly", command=self._on_device_changed,
        )
        self.spk_combo.pack(side="right", padx=4, pady=5)
        ctk.CTkLabel(
            self.device_bar_frame, text="Speaker:", text_color=TEXT_SECONDARY,
        ).pack(side="right", padx=(6, 2))

        self.mic_combo = ctk.CTkComboBox(
            self.device_bar_frame, values=["Default Microphone"],
            width=195, height=26,
            fg_color=CLUSTER_BG, border_color=CLUSTER_BORDER, border_width=1,
            button_color=CLUSTER_BG, button_hover_color=CLUSTER_HOVER_BG,
            state="readonly", command=self._on_device_changed,
        )
        self.mic_combo.pack(side="right", padx=4, pady=5)
        ctk.CTkLabel(
            self.device_bar_frame, text="Mic:", text_color=TEXT_SECONDARY,
        ).pack(side="right", padx=(4, 2))

        # Left side: Two-line status readout (pack_propagate(False) keeps right controls pinned)
        self.status_text_frame = ctk.CTkFrame(self.status_bar, fg_color="transparent")
        self.status_text_frame.pack(side="left", fill="both", expand=True, padx=(10, 4), pady=3)
        self.status_text_frame.pack_propagate(False)

        status_font = ctk.CTkFont(family=MONO_FONT_FAMILY, size=11)
        self.status_label = ctk.CTkLabel(
            self.status_text_frame, text="Ready. Click Start to begin listening.",
            font=status_font, text_color=TEXT_PRIMARY, anchor="w", height=18,
        )
        self.status_label.pack(side="top", fill="x", anchor="w", pady=(1, 0))

        self.output_label = ctk.CTkLabel(
            self.status_text_frame, text="Output: —",
            font=status_font, text_color=TEXT_SECONDARY, anchor="w", height=18,
        )
        self.output_label.pack(side="top", fill="x", anchor="w", pady=(0, 1))
        self.output_tooltip = Tooltip(self.output_label, "")

    def _set_status(self, line1: str, output_path: Optional[str] = None) -> None:
        """Update the two-line status bar readout."""
        self.status_label.configure(text=line1)
        if output_path is not None:
            out_text = f"Output: {output_path}" if output_path else "Output: —"
            self.output_label.configure(text=out_text)
            self.output_tooltip.text = str(output_path) if output_path else ""

    @staticmethod
    def _device_label(d: dict) -> str:
        return f"[{d['index']}] {d['name']}"

    @staticmethod
    def _label_name(label: str) -> str:
        """Strip the '[index] ' prefix so devices can be matched by name when indices shift."""
        return label.split("] ", 1)[1] if label.startswith("[") and "] " in label else label

    def _load_devices(self):
        try:
            p = pyaudio.PyAudio()
            mics, speakers = get_audio_devices(p)
            p.terminate()
            self._apply_device_lists(mics, speakers)
        except Exception as e:
            self._set_status(f"Device load warning: {e}")

    def _apply_device_lists(self, mics: list, speakers: list) -> list[str]:
        """Repopulate both dropdowns, preserving the current selection by device name.

        Returns a list of human-readable notes (e.g. selection fell back to default).
        """
        notes: list[str] = []
        for combo, devices, attr, kind in (
            (self.mic_combo, mics, "_mics_map", "Mic"),
            (self.spk_combo, speakers, "_spks_map", "Speaker"),
        ):
            prev_label = combo.get()
            prev_name = self._label_name(prev_label)
            had_real_selection = prev_label in getattr(self, attr)

            new_map = {self._device_label(d): d["index"] for d in devices}
            setattr(self, attr, new_map)
            labels = list(new_map.keys())
            if not labels:
                continue
            combo.configure(values=labels)

            match = next((lbl for lbl in labels if self._label_name(lbl) == prev_name), None)
            if match:
                combo.set(match)
            else:
                combo.set(labels[0])
                if had_real_selection:
                    notes.append(f"{kind} '{prev_name}' not found; switched to '{self._label_name(labels[0])}'")
        return notes

    def _refresh_devices_async(self, reason: str = "manual"):
        """Rescan audio hardware in a background thread so the GUI never freezes."""
        if self._refreshing:
            return
        self._refreshing = True
        self._set_rescan_busy(True)
        self._set_status("Scanning audio devices...")
        session = self.session
        mic_name = self._label_name(self.mic_combo.get())
        spk_name = self._label_name(self.spk_combo.get())

        def _worker():
            try:
                if session is not None:
                    # PortAudio only rescans once all PyAudio instances are terminated,
                    # so the running session must recycle its own instance. Devices are
                    # matched by name because indices can shift after a hot-plug.
                    mics, speakers = session.reload_audio_devices(
                        mic_name=mic_name, speaker_name=spk_name,
                    )
                else:
                    p = pyaudio.PyAudio()
                    try:
                        mics, speakers = get_audio_devices(p)
                    finally:
                        p.terminate()
                self.device_queue.put(("ok", reason, mics, speakers, session is not None))
            except Exception as e:
                self.device_queue.put(("error", reason, str(e), None, session is not None))

        threading.Thread(target=_worker, daemon=True).start()

    def _set_rescan_busy(self, busy: bool) -> None:
        """Toggle the Rescan button between its normal (teal) and scanning (amber) looks."""
        if busy:
            self.refresh_btn.configure(
                text="⟳ Scanning…", state="disabled", fg_color=BTN_BUSY_FG,
            )
        else:
            self.refresh_btn.configure(
                text="⟳ Rescan", state="normal", fg_color=BTN_ACCENT_FG,
            )

    def _on_device_lists_refreshed(self, status, reason, mics, speakers, was_running):
        self._refreshing = False
        self._set_rescan_busy(False)
        if status == "error":
            self._set_status(f"Device refresh failed: {mics}")
            return

        self.refresh_tooltip.text = (
            f"{RESCAN_TOOLTIP}\nLast scan {datetime.now():%H:%M:%S} — "
            f"{len(mics)} mic{'s' if len(mics) != 1 else ''}, "
            f"{len(speakers)} speaker{'s' if len(speakers) != 1 else ''}"
        )

        notes = self._apply_device_lists(mics, speakers)
        if reason == "switch":
            msg = f"Switched devices → Mic: {self._label_name(self.mic_combo.get())} | Speaker: {self._label_name(self.spk_combo.get())}"
        elif reason == "hotplug":
            msg = f"Audio devices changed — list updated ({len(mics)} mics, {len(speakers)} speakers)"
        else:
            msg = f"Device list refreshed ({len(mics)} mics, {len(speakers)} speakers)"
        if notes:
            msg += " | " + "; ".join(notes)
        if was_running and self.session is not None:
            self._set_status(
                f"Transcribing... [ASR: {self.session.engine_name} | Translate: {self.session.tname}] — {msg}",
                output_path=str(self.session.out_path),
            )
        else:
            self._set_status(msg)

    def _on_device_changed(self, _choice=None):
        """Live-switch the capture device while transcribing (no-op when idle)."""
        if self.session is not None and self.is_running:
            self._refresh_devices_async(reason="switch")

    def _start_hotplug_watcher(self):
        """Poll the winmm hardware signature on a daemon thread (keeps the Tk loop smooth)."""
        def _watch():
            last = get_device_topology_signature()
            while not self._watcher_stop.wait(2.5):
                try:
                    sig = get_device_topology_signature()
                except Exception:
                    continue
                if sig and sig != last:
                    last = sig
                    self.hotplug_queue.put(True)

        threading.Thread(target=_watch, daemon=True).start()

    def toggle_session(self):
        if not self.is_running:
            self._start_session()
        else:
            self._stop_session()

    def _start_session(self):
        mic_idx = self._mics_map.get(self.mic_combo.get())
        spk_idx = self._spks_map.get(self.spk_combo.get())

        try:
            self.session = TranscriptionSession(
                translator_choice=self.trans_combo.get(),
                language=self.lang_combo.get(),
                en_engine=self.en_engine_combo.get(),
                mic_device_index=mic_idx,
                speaker_device_index=spk_idx,
                enable_mic=self.mic_enabled,
                enable_speaker=self.spk_enabled,
                on_entry=self.event_queue.put,
                on_activity=lambda src, sp, lvl: self.activity_queue.put((src, sp, lvl)),
            )
            self.session.start()
            self.is_running = True
            self.start_btn.configure(
                text="⏹ Stop", fg_color=BTN_STOP_FG, hover_color=BTN_STOP_HOVER, state="normal",
            )
            self._set_status(
                f"Transcribing... [ASR: {self.session.engine_name} | Translate: {self.session.tname}]",
                output_path=str(self.session.out_path),
            )
            self.lang_combo.configure(state="disabled")
            self.en_engine_combo.configure(state="disabled")
            self.trans_combo.configure(state="disabled")
        except Exception as e:
            self._set_status(f"Startup Error: {e}")
            self.lang_combo.configure(state="readonly")
            self._on_lang_changed(self.lang_combo.get())
            self.trans_combo.configure(state="readonly")
            if self.session:
                try:
                    self.session.stop()
                except Exception:
                    pass
                self.session = None

    def _stop_session(self):
        self.start_btn.configure(state="disabled", text="Stopping...")
        session_to_stop = self.session
        self.session = None
        self.is_running = False

        def _async_stop():
            if session_to_stop:
                session_to_stop.stop()
            self.after(0, self._on_stop_complete)

        threading.Thread(target=_async_stop, daemon=True).start()

    def _on_stop_complete(self):
        self._finalize_pending_interims()
        self.start_btn.configure(
            text="▶ Start", fg_color=BTN_START_FG, hover_color=BTN_START_HOVER, state="normal",
        )
        self._set_status("Stopped.")
        self.mic_led.configure(text=f"{LED_IDLE} Idle")
        self.spk_led.configure(text=f"{LED_IDLE} Idle")
        self.mic_combo.configure(state="readonly")
        self.spk_combo.configure(state="readonly")
        self.lang_combo.configure(state="readonly")
        self._on_lang_changed(self.lang_combo.get())
        self.trans_combo.configure(state="readonly")

    def _process_events(self):
        now = time.time()
        activity_count = 0
        while not self.activity_queue.empty() and activity_count < 25:
            src, is_speech, _ = self.activity_queue.get_nowait()
            if is_speech:
                if src == "ME":
                    self._last_mic_speech = now
                    self.mic_led.configure(text=f"{LED_ACTIVE} Speaking")
                else:
                    self._last_spk_speech = now
                    self.spk_led.configure(text=f"{LED_ACTIVE} Speaking")
            activity_count += 1

        if self.is_running:
            if self.mic_enabled:
                if now - self._last_mic_speech > 0.6:
                    self.mic_led.configure(text=f"{LED_IDLE} Listening")
            else:
                self.mic_led.configure(text=f"{LED_IDLE} Disabled")

            if self.spk_enabled:
                if now - self._last_spk_speech > 0.6:
                    self.spk_led.configure(text=f"{LED_IDLE} Listening")
            else:
                self.spk_led.configure(text=f"{LED_IDLE} Disabled")

        while not self.event_queue.empty():
            entry = self.event_queue.get_nowait()
            if entry.id in self._entry_index_by_id:
                idx = self._entry_index_by_id[entry.id]
                self.entries[idx] = entry
            else:
                self._entry_index_by_id[entry.id] = len(self.entries)
                self.entries.append(entry)
            self._render_entry(entry)

        while not self.device_queue.empty():
            self._on_device_lists_refreshed(*self.device_queue.get_nowait())

        if not self.hotplug_queue.empty():
            while not self.hotplug_queue.empty():
                self.hotplug_queue.get_nowait()
            if self._refreshing:
                self.hotplug_queue.put(True)  # retry once the current scan finishes
            else:
                self._refresh_devices_async(reason="hotplug")

        self.after(60, self._process_events)

    @staticmethod
    def _upsert_textbox_block(
        textbox: ctk.CTkTextbox,
        entry_id: str,
        block_text: str,
        is_final: bool,
    ) -> None:
        """Insert or update an utterance block in-place using Tkinter text tags."""
        tag = f"entry_{entry_id}"
        ranges = textbox.tag_ranges(tag)
        if ranges:
            start_idx, end_idx = ranges[0], ranges[1]
            textbox.delete(start_idx, end_idx)
            if is_final:
                textbox.insert(start_idx, block_text)
                textbox.tag_delete(tag)
            else:
                textbox.insert(start_idx, block_text, (tag,))
        else:
            if is_final:
                textbox.insert("end", block_text)
            else:
                textbox.insert("end", block_text, (tag,))
        textbox.see("end")

    def _finalize_pending_interims(self, source: Optional[str] = None) -> None:
        """Lock in any active interim blocks when a channel is disabled or session stops."""
        for e in self.entries:
            if not e.is_final and (source is None or e.source == source):
                e.is_final = True
                self._render_entry(e)

    @staticmethod
    def _matches_filter(mode: str, source: str) -> bool:
        if mode in ("Mic Only", "Microphone Only"):
            return source == "ME"
        if mode == "Speaker Only":
            return source == "OTHERS"
        return True

    def _render_entry(self, entry: TranscriptEntry):
        col_block = format_entry_block(entry, include_source=False)
        uni_block = format_entry_block(entry, include_source=True)

        if entry.source == "ME":
            self._upsert_textbox_block(self.mic_textbox, entry.id, col_block, entry.is_final)
        else:
            self._upsert_textbox_block(self.spk_textbox, entry.id, col_block, entry.is_final)

        mode = self.filter_combo.get()
        if self._matches_filter(mode, entry.source):
            self._upsert_textbox_block(self.unified_textbox, entry.id, uni_block, entry.is_final)

    def _rebuild_unified_textbox(self):
        self.unified_textbox.delete("1.0", "end")
        mode = self.filter_combo.get()
        for e in self.entries:
            if self._matches_filter(mode, e.source):
                self._upsert_textbox_block(
                    self.unified_textbox,
                    e.id,
                    format_entry_block(e, include_source=True),
                    e.is_final,
                )
        self.unified_textbox.see("end")

    def _on_filter_changed(self, choice):
        self.mic_frame.pack_forget()
        self.spk_frame.pack_forget()

        if choice in ("Mic Only", "Microphone Only"):
            self.mic_frame.pack(side="left", fill="both", expand=True)
        elif choice == "Speaker Only":
            self.spk_frame.pack(side="right", fill="both", expand=True)
        else:
            self.mic_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
            self.spk_frame.pack(side="right", fill="both", expand=True, padx=(4, 0))

        self._rebuild_unified_textbox()

    def _on_lang_changed(self, choice: str) -> None:
        """Enable the EN Model selector only when Lang = en."""
        if choice == "en":
            self.en_engine_combo.configure(state="readonly")
        else:
            self.en_engine_combo.configure(state="disabled")

    def _update_view_toggle(self) -> None:
        """Redraw the Dual Column / Unified Timeline segmented icon pill."""
        is_dual = self.layout_mode == "dual"
        dual_bg = VIEW_ACTIVE_BG if is_dual else VIEW_PILL_BG
        uni_bg = VIEW_PILL_BG if is_dual else VIEW_ACTIVE_BG
        dual_fg = VIEW_ACTIVE_FG if is_dual else VIEW_INACTIVE_FG
        uni_fg = VIEW_INACTIVE_FG if is_dual else VIEW_ACTIVE_FG

        self.dual_seg.configure(fg_color=dual_bg)
        self.dual_canvas.configure(bg=dual_bg)
        self.dual_canvas.delete("all")
        self.dual_canvas.create_rectangle(2, 2, 14, 12, outline=dual_fg, width=1.5)
        self.dual_canvas.create_line(8, 2, 8, 12, fill=dual_fg, width=1.5)

        self.uni_seg.configure(fg_color=uni_bg)
        self.uni_canvas.configure(bg=uni_bg)
        self.uni_canvas.delete("all")
        for y in (3, 7, 11):
            self.uni_canvas.create_line(2, y, 14, y, fill=uni_fg, width=2, capstyle="round")

    def _on_layout_changed(self, choice):
        if choice == "Unified Timeline":
            self.layout_mode = "unified"
            self.dual_container.pack_forget()
            self.unified_frame.pack(fill="both", expand=True)
            self._rebuild_unified_textbox()
        else:
            self.layout_mode = "dual"
            self.unified_frame.pack_forget()
            self.dual_container.pack(fill="both", expand=True)
        self._update_view_toggle()

    def _toggle_pin(self):
        self.topmost_var.set(not self.topmost_var.get())
        self._toggle_topmost()

    def _set_pin_hover(self, hovered: bool):
        self._pin_hovered = hovered
        self._update_pin_button()

    def _update_pin_button(self):
        is_pinned = self.topmost_var.get()
        bg = CLUSTER_HOVER_BG if (self._pin_hovered or is_pinned) else CLUSTER_BG
        fg = VIEW_ACTIVE_FG if is_pinned else (ICON_HOVER_FG if self._pin_hovered else VIEW_INACTIVE_FG)
        self.pin_btn.configure(fg_color=bg)
        self.pin_canvas.configure(bg=bg)
        self.pin_canvas.delete("all")
        # Draw thumbtack / pin icon
        self.pin_canvas.create_line(5, 2, 11, 2, fill=fg, width=1.5)
        self.pin_canvas.create_line(6, 2, 6, 7, 4, 9, 12, 9, 10, 7, 10, 2, fill=fg, width=1.4)
        self.pin_canvas.create_line(8, 9, 8, 14, fill=fg, width=1.5)
        if is_pinned:
            self.pin_canvas.create_oval(12, 1, 15, 4, fill=VIEW_ACTIVE_FG, outline="")

    def _toggle_topmost(self):
        self.attributes("-topmost", self.topmost_var.get())
        self._update_pin_button()

    def _clear_transcripts(self):
        self.entries.clear()
        self._entry_index_by_id.clear()
        self.mic_textbox.delete("1.0", "end")
        self.spk_textbox.delete("1.0", "end")
        self.unified_textbox.delete("1.0", "end")

    def _toggle_mic_channel(self):
        """Toggle audio capture for Microphone (ME)."""
        self.mic_enabled = not self.mic_enabled
        if self.mic_enabled:
            self.mic_toggle_btn.configure(
                text="Disable", fg_color=MIC_BTN_DISABLE_FG, hover_color=MIC_BTN_DISABLE_HOVER,
            )
            self.mic_header.configure(fg_color=MIC_HEADER_COLOR)
            self.mic_led.configure(text=f"{LED_IDLE} Listening" if self.is_running else f"{LED_IDLE} Idle")
        else:
            self.mic_toggle_btn.configure(
                text="Enable", fg_color=MIC_BTN_ENABLE_FG, hover_color=MIC_BTN_ENABLE_HOVER,
            )
            self.mic_header.configure(fg_color=MIC_HEADER_COLOR)
            self.mic_led.configure(text=f"{LED_IDLE} Disabled")
            self._finalize_pending_interims("ME")

        if self.session:
            self.session.set_channel_enabled("ME", self.mic_enabled)

    def _toggle_spk_channel(self):
        """Toggle audio capture for Speaker / System (OTHERS)."""
        self.spk_enabled = not self.spk_enabled
        if self.spk_enabled:
            self.spk_toggle_btn.configure(
                text="Disable", fg_color=SPK_BTN_DISABLE_FG, hover_color=SPK_BTN_DISABLE_HOVER,
            )
            self.spk_header.configure(fg_color=SPK_HEADER_COLOR)
            self.spk_led.configure(text=f"{LED_IDLE} Listening" if self.is_running else f"{LED_IDLE} Idle")
        else:
            self.spk_toggle_btn.configure(
                text="Enable", fg_color=SPK_BTN_ENABLE_FG, hover_color=SPK_BTN_ENABLE_HOVER,
            )
            self.spk_header.configure(fg_color=SPK_HEADER_COLOR)
            self.spk_led.configure(text=f"{LED_IDLE} Disabled")
            self._finalize_pending_interims("OTHERS")

        if self.session:
            self.session.set_channel_enabled("OTHERS", self.spk_enabled)

    def _copy_transcripts(self):
        full_text = "\n".join(format_entry_block(e, include_source=True) for e in self.entries)
        if not full_text.strip():
            messagebox.showinfo("Copy Transcript", "No transcript entries to copy.")
            return
        self.clipboard_clear()
        self.clipboard_append(full_text)
        self.update()
        messagebox.showinfo("Copy Transcript", "Transcript copied to clipboard!")

    def _save_transcripts(self):
        full_text = "\n".join(format_entry_block(e, include_source=True) for e in self.entries)
        if not full_text.strip():
            messagebox.showinfo("Save Transcript", "No transcript entries to save.")
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=f"transcript_export_{datetime.now():%Y%m%d_%H%M%S}.txt",
        )
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_text)
            messagebox.showinfo("Save Transcript", f"Transcript successfully saved to:\n{file_path}")

    def _font_increase(self):
        if self.font_size < FONT_SIZE_MAX:
            self.font_size += 1
            self._apply_font_size()

    def _font_decrease(self):
        if self.font_size > FONT_SIZE_MIN:
            self.font_size -= 1
            self._apply_font_size()

    def _apply_font_size(self):
        font = (FONT_FAMILY, self.font_size)
        self.mic_textbox.configure(font=font)
        self.spk_textbox.configure(font=font)
        self.unified_textbox.configure(font=font)
        self.font_label.configure(text=f"{self.font_size}pt")

    def destroy(self):
        self._watcher_stop.set()
        if self.session:
            self.session.stop()
        super().destroy()
