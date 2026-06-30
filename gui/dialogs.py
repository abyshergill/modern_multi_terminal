from __future__ import annotations
import os
import re
import webbrowser
import customtkinter as ctk
import serial.tools.list_ports
from pathlib import Path
from tkinter import filedialog, messagebox
from core.presets import TMPL_SSH_LOGIN, TMPL_PY_AUTO, TMPL_SERIAL_AT, TMPL_TTL_BATCH

BAUD_RATES = ["300", "1200", "2400", "4800", "9600", "14400", "19200", "38400", "57600", "115200", "230400", "460800", "921600", "Custom"]
TERMINAL_ACCENT = "#46f0a6"
TERMINAL_MUTED = "#7b8b99"

class SamplesDialog(ctk.CTkToplevel):
    def __init__(self, app: object):
        super().__init__(app)
        self.title("Help & Preset Repository"); self.geometry("660x560"); self.resizable(False, False); self.transient(app); self.grab_set()
        ctk.CTkLabel(self, text="Preset Script Templates Repository", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=20, pady=(18, 10))
        scroll = ctk.CTkScrollableFrame(self); scroll.pack(fill="both", expand=True, padx=20, pady=5)
        items = [
            ("SSH Auto-Login Macro (.ttl)", "Standard Tera Term TTL macro to auto-enter credentials.", TMPL_SSH_LOGIN, ".ttl"),
            ("Python Terminal Automation (.py)", "Send commands, pause, and log output sequentially.", TMPL_PY_AUTO, ".py"),
            ("Serial AT Command Tester (.py)", "Automated routine to query hardware modems.", TMPL_SERIAL_AT, ".py"),
            ("Batch Command Delay (.ttl)", "Pass multiple lines with timed execution pauses.", TMPL_TTL_BATCH, ".ttl")
        ]
        for title, desc, code, ext in items:
            card = ctk.CTkFrame(scroll, fg_color="#121a24"); card.pack(fill="x", pady=6, padx=4); card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=TERMINAL_ACCENT).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
            ctk.CTkLabel(card, text=desc, text_color=TERMINAL_MUTED).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
            ctk.CTkButton(card, text="Download", width=95, fg_color="#2f6f95", command=lambda c=code, e=ext, t=title: self._save(t, c, e)).grid(row=0, column=1, rowspan=2, padx=14, pady=10)

        more_frame = ctk.CTkFrame(scroll, fg_color="#182533", border_width=1, border_color="#2b4763"); more_frame.pack(fill="x", pady=(14, 6), padx=4); more_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(more_frame, text="Need Advanced Scrapers?", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(more_frame, text="Explore community user scripts and enterprise scrapers online.", text_color=TERMINAL_MUTED).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
        ctk.CTkButton(more_frame, text="🌐 More Scripts", width=110, fg_color="#7656b7", hover_color="#8b68d4", command=lambda: webbrowser.open("https://github.com/abyshergill/mmte/scripts/")).grid(row=0, column=1, rowspan=2, padx=14)

        creator_card = ctk.CTkFrame(scroll, fg_color="#0d141c"); creator_card.pack(fill="x", pady=(6, 12), padx=4)
        ctk.CTkLabel(creator_card, text="⚙️ Creator Information", font=ctk.CTkFont(size=13, weight="bold"), text_color=TERMINAL_ACCENT).pack(anchor="w", padx=14, pady=(8, 2))
        dev_btn = ctk.CTkButton(creator_card, text="👤 Engineered by Aby Shergill (Click to Contact) ↗", font=ctk.CTkFont(size=11, underline=True), fg_color="transparent", text_color="#38b6ff", hover_color="#142230", anchor="w", height=22, command=lambda: webbrowser.open("https://github.com/abyshergill"))
        dev_btn.pack(anchor="w", padx=8, pady=(0, 2))
        ctk.CTkLabel(creator_card, text="Build v2.4 by Aby Shergill  ·  BSD License", font=ctk.CTkFont(size=11), text_color=TERMINAL_MUTED).pack(anchor="w", padx=14, pady=(0, 8))
        ctk.CTkButton(self, text="Close", fg_color="#3a3f45", command=self.destroy).pack(anchor="e", padx=20, pady=12)

    def _save(self, name: str, content: str, ext: str):
        safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
        path = filedialog.asksaveasfilename(title=f"Save {name}", defaultextension=ext, initialfile=f"{safe}{ext}", filetypes=[(f"{ext.upper()} Script", f"*{ext}"), ("All Files", "*.*")], parent=self)
        if path: Path(path).write_text(content.strip() + "\n", encoding="utf-8"); messagebox.showinfo("Saved", f"Template saved successfully to:\n{path}", parent=self)

class RenameDialog(ctk.CTkToplevel):
    def __init__(self, app: object, current_name: str):
        super().__init__(app); self.result: str | None = None; self.title("Rename Terminal"); self.geometry("380x180"); self.resizable(False, False); self.transient(app); self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Enter New Terminal Name:", font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        self.name_var = ctk.StringVar(value=current_name); entry = ctk.CTkEntry(self, textvariable=self.name_var, width=340); entry.grid(row=1, column=0, padx=20, pady=10, sticky="ew"); entry.focus_set()
        buttons = ctk.CTkFrame(self, fg_color="transparent"); buttons.grid(row=2, column=0, padx=20, pady=(15, 10), sticky="ew"); buttons.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(buttons, text="Cancel", fg_color="#3a3f45", command=self.destroy).grid(row=0, column=0, padx=5, sticky="ew")
        ctk.CTkButton(buttons, text="Save", command=self._ok).grid(row=0, column=1, padx=5, sticky="ew")
    def _ok(self): self.result = self.name_var.get().strip(); self.destroy()

class SSHDialog(ctk.CTkToplevel):
    def __init__(self, app: object):
        super().__init__(app); self.app = app; self.result: dict | None = None; self.title("Connect SSH"); self.geometry("460x430"); self.resizable(False, False); self.transient(app); self.grab_set()
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="SSH Connection", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, columnspan=2, pady=(18, 12), sticky="w", padx=20)
        self.profile_var = ctk.StringVar(value="")
        profiles = [""] + sorted(self.app.profile_store.profiles.keys())
        ctk.CTkLabel(self, text="Saved profile").grid(row=1, column=0, padx=(20, 8), pady=6, sticky="w")
        ctk.CTkOptionMenu(self, variable=self.profile_var, values=profiles, command=self._load_profile).grid(row=1, column=1, padx=20, pady=6, sticky="ew")
        self.profile_name, self.host, self.username, self.password, self.port, self.save_profile = ctk.StringVar(), ctk.StringVar(), ctk.StringVar(), ctk.StringVar(), ctk.StringVar(value="22"), ctk.BooleanVar(value=True)
        rows = [("Profile name", self.profile_name, False), ("Host/IP", self.host, False), ("Username", self.username, False), ("Password", self.password, True), ("Port", self.port, False)]
        for idx, (label, var, secret) in enumerate(rows, start=2):
            ctk.CTkLabel(self, text=label).grid(row=idx, column=0, padx=(20, 8), pady=6, sticky="w")
            ctk.CTkEntry(self, textvariable=var, show="*" if secret else None).grid(row=idx, column=1, padx=20, pady=6, sticky="ew")
        ctk.CTkCheckBox(self, text="Save/update profile", variable=self.save_profile).grid(row=7, column=1, padx=20, pady=8, sticky="w")
        buttons = ctk.CTkFrame(self, fg_color="transparent"); buttons.grid(row=8, column=0, columnspan=2, pady=18, padx=20, sticky="ew"); buttons.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(buttons, text="Cancel", fg_color="#3a3f45", command=self.destroy).grid(row=0, column=0, padx=6, sticky="ew")
        ctk.CTkButton(buttons, text="Connect", command=self._ok).grid(row=0, column=1, padx=6, sticky="ew")

    def _load_profile(self, name: str):
        if not name: return
        p = self.app.profile_store.profiles.get(name, {})
        self.profile_name.set(name); self.host.set(p.get("host", "")); self.username.set(p.get("username", "")); self.port.set(str(p.get("port", "22")))

    def _ok(self):
        if not self.host.get().strip(): messagebox.showerror("Missing host", "Enter the SSH host/IP.", parent=self); return
        try: port = int(self.port.get() or "22")
        except ValueError: messagebox.showerror("Invalid port", "Port must be numeric.", parent=self); return
        self.result = {"profile_name": self.profile_name.get().strip(), "host": self.host.get().strip(), "username": self.username.get().strip(), "password": self.password.get(), "port": port, "save": self.save_profile.get()}; self.destroy()

class SerialDialog(ctk.CTkToplevel):
    def __init__(self, app: object):
        super().__init__(app); self.result: dict | None = None; self.title("Connect Serial"); self.geometry("500x390"); self.resizable(False, False); self.transient(app); self.grab_set()
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Serial Connection", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, columnspan=2, pady=(18, 12), padx=20, sticky="w")
        raw_ports, self.port_map, combo_values = serial.tools.list_ports.comports(), {}, []
        if raw_ports:
            for p in raw_ports: self.port_map[p.description] = p.device; combo_values.append(p.description)
        else: fallback = "COM1" if os.name == "nt" else "/dev/ttyUSB0"; self.port_map[fallback] = fallback; combo_values.append(fallback)
        preset_rates = [rate for rate in BAUD_RATES if rate != "Custom"]
        self.port_var, self.baud_mode, self.baud_var, self.custom_baud = ctk.StringVar(value=combo_values[0]), ctk.StringVar(value="preset"), ctk.StringVar(value="115200"), ctk.StringVar()
        ctk.CTkLabel(self, text="Port").grid(row=1, column=0, padx=(20, 8), pady=7, sticky="w")
        ctk.CTkComboBox(self, variable=self.port_var, values=combo_values).grid(row=1, column=1, padx=20, pady=7, sticky="ew")
        ctk.CTkLabel(self, text="Baud rate mode").grid(row=2, column=0, padx=(20, 8), pady=7, sticky="w")
        mode_frame = ctk.CTkFrame(self, fg_color="transparent"); mode_frame.grid(row=2, column=1, padx=20, pady=7, sticky="ew")
        ctk.CTkRadioButton(mode_frame, text="Preset", variable=self.baud_mode, value="preset", command=self._update_baud_mode).pack(side="left", padx=(0, 18))
        ctk.CTkRadioButton(mode_frame, text="Custom", variable=self.baud_mode, value="custom", command=self._update_baud_mode).pack(side="left")
        ctk.CTkLabel(self, text="Preset baud").grid(row=3, column=0, padx=(20, 8), pady=7, sticky="w")
        self.baud_combo = ctk.CTkComboBox(self, variable=self.baud_var, values=preset_rates); self.baud_combo.grid(row=3, column=1, padx=20, pady=7, sticky="ew")
        ctk.CTkLabel(self, text="Custom baud").grid(row=4, column=0, padx=(20, 8), pady=7, sticky="w")
        self.custom_baud_entry = ctk.CTkEntry(self, textvariable=self.custom_baud, placeholder_text="Example: 250000"); self.custom_baud_entry.grid(row=4, column=1, padx=20, pady=7, sticky="ew")
        buttons = ctk.CTkFrame(self, fg_color="transparent"); buttons.grid(row=5, column=0, columnspan=2, pady=26, padx=20, sticky="ew"); buttons.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(buttons, text="Cancel", fg_color="#3a3f45", command=self.destroy).grid(row=0, column=0, padx=6, sticky="ew")
        ctk.CTkButton(buttons, text="Connect", command=self._ok).grid(row=0, column=1, padx=6, sticky="ew")
        self._update_baud_mode()

    def _update_baud_mode(self):
        if self.baud_mode.get() == "preset": self.baud_combo.configure(state="normal"); self.custom_baud_entry.configure(state="disabled")
        else: self.baud_combo.configure(state="disabled"); self.custom_baud_entry.configure(state="normal"); self.custom_baud_entry.focus_set()

    def _ok(self):
        baud_text = self.custom_baud.get().strip() if self.baud_mode.get() == "custom" else self.baud_var.get().strip()
        try:
            baud = int(baud_text)
            if baud <= 0: raise ValueError
        except ValueError: messagebox.showerror("Invalid baud rate", "Baud rate must be numeric.", parent=self); return
        chosen_display = self.port_var.get().strip()
        self.result = {"port": self.port_map.get(chosen_display, chosen_display), "baud": baud}; self.destroy()

class TelnetDialog(ctk.CTkToplevel):
    def __init__(self, app: object):
        super().__init__(app); self.result: dict | None = None; self.title("Connect Telnet"); self.geometry("400x220"); self.resizable(False, False); self.transient(app); self.grab_set()
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Telnet Connection", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, columnspan=2, pady=(18, 12), padx=20, sticky="w")
        self.host_var, self.port_var = ctk.StringVar(), ctk.StringVar(value="23")
        ctk.CTkLabel(self, text="Host / IP").grid(row=1, column=0, padx=(20, 8), pady=8, sticky="w")
        ctk.CTkEntry(self, textvariable=self.host_var, placeholder_text="192.168.1.1").grid(row=1, column=1, padx=20, pady=8, sticky="ew")
        ctk.CTkLabel(self, text="Port").grid(row=2, column=0, padx=(20, 8), pady=8, sticky="w")
        ctk.CTkEntry(self, textvariable=self.port_var, width=80).grid(row=2, column=1, padx=20, pady=8, sticky="w")
        btns = ctk.CTkFrame(self, fg_color="transparent"); btns.grid(row=3, column=0, columnspan=2, pady=18, padx=20, sticky="ew"); btns.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(btns, text="Cancel", fg_color="#3a3f45", command=self.destroy).grid(row=0, column=0, padx=5, sticky="ew")
        ctk.CTkButton(btns, text="Connect", command=self._ok).grid(row=0, column=1, padx=5, sticky="ew")
    def _ok(self):
        if not self.host_var.get().strip(): messagebox.showerror("Missing Host", "Enter IP.", parent=self); return
        try: port = int(self.port_var.get().strip() or 23)
        except ValueError: messagebox.showerror("Invalid Port", "Numeric only.", parent=self); return
        self.result = {"host": self.host_var.get().strip(), "port": port}; self.destroy()

class OperatorGateDialog(ctk.CTkToplevel):
    def __init__(self, app: object, script_name: str, reason: str, tail_log: str, event_lock: threading.Event, decision_holder: dict):
        super().__init__(app); self.decision_holder, self.event_lock = decision_holder, event_lock
        self.title("⚠️ Playlist Gate Triggered"); self.geometry("560x340"); self.resizable(False, False); self.transient(app); self.grab_set(); self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="⚠️ Execution Handoff Failed", font=ctk.CTkFont(size=18, weight="bold"), text_color="#ff5722").grid(row=0, column=0, padx=20, pady=(15, 4), sticky="w")
        ctk.CTkLabel(self, text=f"Script: '{Path(script_name).name}'\nReason: {reason}", justify="left", text_color=TERMINAL_MUTED).grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")
        ctk.CTkLabel(self, text="Terminal Output Context (Last 250 chars):", font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=0, padx=20, sticky="w")
        box = ctk.CTkTextbox(self, height=100, fg_color="#0b131c", text_color="#d8f3dc", font=ctk.CTkFont(family="Consolas", size=12)); box.grid(row=3, column=0, padx=20, pady=5, sticky="ew")
        box.insert("end", tail_log if tail_log.strip() else "[No recent terminal output]"); box.configure(state="disabled")
        btns = ctk.CTkFrame(self, fg_color="transparent"); btns.grid(row=4, column=0, padx=20, pady=18, sticky="ew"); btns.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkButton(btns, text="+15s More Time", fg_color="#2f6f95", command=lambda: self._choose("EXTEND")).grid(row=0, column=0, padx=4, sticky="ew")
        ctk.CTkButton(btns, text="Force Next Script", fg_color="#d16232", command=lambda: self._choose("FORCE")).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(btns, text="Abort Playlist", fg_color="#8a2d3b", command=lambda: self._choose("ABORT")).grid(row=0, column=2, padx=4, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", lambda: self._choose("ABORT"))
    def _choose(self, action: str): self.decision_holder["choice"] = action; self.event_lock.set(); self.destroy()