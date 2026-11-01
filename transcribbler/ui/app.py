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
    BTN_ACCENT_FG,
    BTN_ACCENT_HOVER,
    BTN_BUSY_FG,
    BTN_NEUTRAL_FG,
    BTN_NEUTRAL_HOVER,
    BTN_START_FG,
    BTN_START_HOVER,
    BTN_STOP_FG,
    BTN_STOP_HOVER,
    FONT_FAMILY,
    FONT_SIZE_DEFAULT,
    FONT_SIZE_MAX,
    FONT_SIZE_MIN,
    LED_ACTIVE,
    LED_IDLE,
    MIC_HEADER_COLOR,
    SPK_HEADER_COLOR,
)
import pyaudiowpatch as pyaudio

RESCAN_TOOLTIP = "Rescan audio devices — detect newly plugged-in USB / Bluetooth headsets"
LANG_TOOLTIP = (
    "auto: SenseVoice-Small (Multilingual EN / Cantonese / Mandarin + Romanization)\n"
    "en: Parakeet-TDT-0.6B-v2 / Moonshine (English Meetings & Podcasts)"
)


class TranscribblerApp(ctk.CTk):
    """Main Transcribbler desktop GUI application."""

    def __init__(self):
        super().__init__()
        self.title("Transcribbler – Real-Time ASR & Translation")
        self.geometry("1100x720")
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
        self.top_frame = ctk.CTkFrame(self, corner_radius=8)
        self.top_frame.pack(fill="x", padx=12, pady=(12, 6))

        row1 = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        row1.pack(fill="x", padx=6, pady=(6, 6))

        self.start_btn = ctk.CTkButton(
            row1, text="▶ Start", width=95,
            fg_color=BTN_START_FG, hover_color=BTN_START_HOVER,
            command=self.toggle_session,
        )
        self.start_btn.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(row1, text="Filter:").pack(side="left", padx=(6, 3))
        self.filter_combo = ctk.CTkComboBox(
            row1,
            values=["All Sources", "Microphone Only", "Speaker Only"],
            width=135, command=self._on_filter_changed, state="readonly",
        )
        self.filter_combo.set("All Sources")
        self.filter_combo.pack(side="left", padx=3)

        ctk.CTkLabel(row1, text="View:").pack(side="left", padx=(6, 3))
        self.layout_combo = ctk.CTkComboBox(
            row1,
            values=["Dual Column", "Unified Timeline"],
            width=130, command=self._on_layout_changed, state="readonly",
        )
        self.layout_combo.set("Dual Column")
        self.layout_combo.pack(side="left", padx=3)

        ctk.CTkLabel(row1, text="Lang:").pack(side="left", padx=(6, 3))
        self.lang_combo = ctk.CTkComboBox(
            row1,
            values=["auto", "en"],
            width=75, state="readonly",
        )
        self.lang_combo.set("auto")
        self.lang_combo.pack(side="left", padx=3)
        self.lang_tooltip = Tooltip(self.lang_combo, LANG_TOOLTIP)

        ctk.CTkLabel(row1, text="Translate:").pack(side="left", padx=(6, 3))
        self.trans_combo = ctk.CTkComboBox(
            row1,
            values=["off", "offline", "azure", "google"],
            width=90, state="readonly",
        )
        self.trans_combo.set("off")
        self.trans_combo.pack(side="left", padx=3)

        self.topmost_var = ctk.BooleanVar(value=False)
        self.topmost_chk = ctk.CTkCheckBox(
            row1, text="Always on Top",
            variable=self.topmost_var, command=self._toggle_topmost,
            width=120,
        )
        self.topmost_chk.pack(side="right", padx=(6, 0))

        self.clear_btn = ctk.CTkButton(
            row1, text="Clear", width=60,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._clear_transcripts,
        )
        self.clear_btn.pack(side="right", padx=3)

        self.save_btn = ctk.CTkButton(
            row1, text="💾 Save", width=68,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._save_transcripts,
        )
        self.save_btn.pack(side="right", padx=3)

        self.copy_btn = ctk.CTkButton(
            row1, text="📋 Copy", width=68,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._copy_transcripts,
        )
        self.copy_btn.pack(side="right", padx=3)

        self.font_minus_btn = ctk.CTkButton(
            row1, text="A-", width=34,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._font_decrease,
        )
        self.font_minus_btn.pack(side="right", padx=2)

        self.font_label = ctk.CTkLabel(row1, text=f"🔤 {self.font_size}pt")
        self.font_label.pack(side="right", padx=2)

        self.font_plus_btn = ctk.CTkButton(
            row1, text="A+", width=34,
            fg_color=BTN_NEUTRAL_FG, hover_color=BTN_NEUTRAL_HOVER,
            command=self._font_increase,
        )
        self.font_plus_btn.pack(side="right", padx=2)

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
            self.mic_header, text="Disable", width=65, height=24,
            fg_color="#343a40", hover_color="#212529", font=ctk.CTkFont(size=12),
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
            self.spk_header, text="Disable", width=65, height=24,
            fg_color="#343a40", hover_color="#212529", font=ctk.CTkFont(size=12),
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
        self.status_bar = ctk.CTkFrame(self, height=36, corner_radius=6)
        self.status_bar.pack(fill="x", padx=12, pady=(0, 8))

        self.status_label = ctk.CTkLabel(
            self.status_bar, text="Ready. Click Start to begin listening.",
        )
        self.status_label.pack(side="left", padx=10)

        self.refresh_btn = ctk.CTkButton(
            self.status_bar, text="⟳ Rescan", width=88,
            fg_color=BTN_ACCENT_FG, hover_color=BTN_ACCENT_HOVER,
            text_color="#ffffff", text_color_disabled="#ffffff",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=lambda: self._refresh_devices_async(reason="manual"),
        )
        self.refresh_btn.pack(side="right", padx=(2, 6), pady=2)
        self.refresh_tooltip = Tooltip(self.refresh_btn, RESCAN_TOOLTIP)

        self.spk_combo = ctk.CTkComboBox(
            self.status_bar, values=["Default Loopback"],
            width=215, state="readonly", command=self._on_device_changed,
        )
        self.spk_combo.pack(side="right", padx=6, pady=2)
        ctk.CTkLabel(self.status_bar, text="Speaker:").pack(side="right", padx=(6, 2))

        self.mic_combo = ctk.CTkComboBox(
            self.status_bar, values=["Default Microphone"],
            width=215, state="readonly", command=self._on_device_changed,
        )
        self.mic_combo.pack(side="right", padx=6, pady=2)
        ctk.CTkLabel(self.status_bar, text="Mic:").pack(side="right", padx=(10, 2))

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
            self.status_label.configure(text=f"Device load warning: {e}")

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
        self.status_label.configure(text="Scanning audio devices...")
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
            self.status_label.configure(text=f"Device refresh failed: {mics}")
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
            msg += f" | Transcribing → {self.session.out_path}"
        self.status_label.configure(text=msg)

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

        self.session = TranscriptionSession(
            translator_choice=self.trans_combo.get(),
            language=self.lang_combo.get(),
            mic_device_index=mic_idx,
            speaker_device_index=spk_idx,
            enable_mic=self.mic_enabled,
            enable_speaker=self.spk_enabled,
            on_entry=self.event_queue.put,
            on_activity=lambda src, sp, lvl: self.activity_queue.put((src, sp, lvl)),
        )
        try:
            self.session.start()
            self.is_running = True
            self.start_btn.configure(
                text="⏹ Stop", fg_color=BTN_STOP_FG, hover_color=BTN_STOP_HOVER, state="normal",
            )
            self.status_label.configure(
                text=(
                    f"Transcribing... [ASR: {self.session.engine_name} | "
                    f"Translate: {self.session.tname}] | Output: {self.session.out_path}"
                ),
            )
            self.lang_combo.configure(state="disabled")
            self.trans_combo.configure(state="disabled")
        except Exception as e:
            self.status_label.configure(text=f"Startup Error: {e}")
            self.lang_combo.configure(state="readonly")
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
        self.status_label.configure(text="Stopped.")
        self.mic_led.configure(text=f"{LED_IDLE} Idle")
        self.spk_led.configure(text=f"{LED_IDLE} Idle")
        self.mic_combo.configure(state="readonly")
        self.spk_combo.configure(state="readonly")
        self.lang_combo.configure(state="readonly")
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

    def _render_entry(self, entry: TranscriptEntry):
        col_block = format_entry_block(entry, include_source=False)
        uni_block = format_entry_block(entry, include_source=True)

        if entry.source == "ME":
            self._upsert_textbox_block(self.mic_textbox, entry.id, col_block, entry.is_final)
        else:
            self._upsert_textbox_block(self.spk_textbox, entry.id, col_block, entry.is_final)

        mode = self.filter_combo.get()
        if mode == "All Sources" or (mode == "Microphone Only" and entry.source == "ME") or (mode == "Speaker Only" and entry.source == "OTHERS"):
            self._upsert_textbox_block(self.unified_textbox, entry.id, uni_block, entry.is_final)

    def _rebuild_unified_textbox(self):
        self.unified_textbox.delete("1.0", "end")
        mode = self.filter_combo.get()
        for e in self.entries:
            if mode == "All Sources" or (mode == "Microphone Only" and e.source == "ME") or (mode == "Speaker Only" and e.source == "OTHERS"):
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

        if choice == "Microphone Only":
            self.mic_frame.pack(side="left", fill="both", expand=True)
        elif choice == "Speaker Only":
            self.spk_frame.pack(side="right", fill="both", expand=True)
        else:
            self.mic_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
            self.spk_frame.pack(side="right", fill="both", expand=True, padx=(4, 0))

        self._rebuild_unified_textbox()

    def _on_layout_changed(self, choice):
        if choice == "Unified Timeline":
            self.dual_container.pack_forget()
            self.unified_frame.pack(fill="both", expand=True)
            self._rebuild_unified_textbox()
        else:
            self.unified_frame.pack_forget()
            self.dual_container.pack(fill="both", expand=True)

    def _toggle_topmost(self):
        self.attributes("-topmost", self.topmost_var.get())

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
            self.mic_toggle_btn.configure(text="Disable", fg_color="#343a40", hover_color="#212529")
            self.mic_header.configure(fg_color=MIC_HEADER_COLOR)
            self.mic_led.configure(text=f"{LED_IDLE} Listening" if self.is_running else f"{LED_IDLE} Idle")
        else:
            self.mic_toggle_btn.configure(text="Enable", fg_color="#2b8a3e", hover_color="#237032")
            self.mic_header.configure(fg_color="#343a40")
            self.mic_led.configure(text=f"{LED_IDLE} Disabled")
            self._finalize_pending_interims("ME")

        if self.session:
            self.session.set_channel_enabled("ME", self.mic_enabled)

    def _toggle_spk_channel(self):
        """Toggle audio capture for Speaker / System (OTHERS)."""
        self.spk_enabled = not self.spk_enabled
        if self.spk_enabled:
            self.spk_toggle_btn.configure(text="Disable", fg_color="#343a40", hover_color="#212529")
            self.spk_header.configure(fg_color=SPK_HEADER_COLOR)
            self.spk_led.configure(text=f"{LED_IDLE} Listening" if self.is_running else f"{LED_IDLE} Idle")
        else:
            self.spk_toggle_btn.configure(text="Enable", fg_color="#2b8a3e", hover_color="#237032")
            self.spk_header.configure(fg_color="#343a40")
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
        self.font_label.configure(text=f"🔤 {self.font_size}pt")

    def destroy(self):
        self._watcher_stop.set()
        if self.session:
            self.session.stop()
        super().destroy()
