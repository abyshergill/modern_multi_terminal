#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt
import json
import os
import queue
import re
import sys
import threading
import posixpath
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter.font as tkfont
import tkinter as tk
import customtkinter as ctk

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.models import TerminalSession
from core.connections import BaseConnection, SSHConnection, SerialConnection, TelnetConnection
from core.script_engine import TeraTermMacroRunner, execute_python_script_sync
from core.theme import TERMINAL_ACCENT, TERMINAL_BG, TERMINAL_FG
from core.sftp_hops import get_active_sftp
from gui.dialogs import SSHDialog, SerialDialog, TelnetDialog, RenameDialog, SamplesDialog
from gui.daw_manager import MultiScriptDialog
from gui.sftp_dialog import SFTPBrowserDialog

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

APP_NAME = "Modern Multi Terminal Emulator"
CONFIG_DIR = Path.home() / ".modern_multi_terminal_emulator"
PROFILES_FILE = CONFIG_DIR / "ssh_profiles.json"
LOG_DIR = CONFIG_DIR / "logs"


class ProfileStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.profiles: dict[str, dict] = self.load()

    def load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.profiles, f, indent=2)

    def upsert(self, name: str, data: dict) -> None:
        self.profiles[name] = data
        self.save()

    def delete(self, name: str) -> None:
        self.profiles.pop(name, None)
        self.save()

if DND_AVAILABLE:
    class _AppBase(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    _AppBase = ctk.CTk

class TerminalApp(_AppBase):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(APP_NAME)
        self.geometry("1340x780")
        self.minsize(1020, 620)

        icon_path = Path("assets/icon.ico")
        if icon_path.exists():
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.profile_store = ProfileStore(PROFILES_FILE)
        self.sessions: list[TerminalSession] = []
        self.active_session: TerminalSession | None = None
        self.session_list_widgets: list[ctk.CTkFrame] = []
        self._build_ui()
        self.new_terminal()
        self.after(40, self.poll_queues)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=245, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)
        ctk.CTkLabel(self.sidebar, text="Terminals", font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, padx=16, pady=(18, 10), sticky="w")
        ctk.CTkButton(self.sidebar, text="+ New Terminal", command=self.new_terminal).grid(row=1, column=0, padx=14, pady=5, sticky="ew")
        ctk.CTkButton(self.sidebar, text="Rename Selected", fg_color="#2f6f95", command=self.rename_terminal).grid(row=2, column=0, padx=14, pady=5, sticky="ew")
        ctk.CTkButton(self.sidebar, text="Close Selected", fg_color="#8a2d3b", hover_color="#a63d4e", command=self.close_current_terminal).grid(row=3, column=0, padx=14, pady=5, sticky="ew")
        self.session_list = ctk.CTkScrollableFrame(self.sidebar, label_text="Open sessions")
        self.session_list.grid(row=4, column=0, padx=12, pady=(10, 12), sticky="nsew")

        self.toolbar = ctk.CTkFrame(self, corner_radius=0, height=58)
        self.toolbar.grid(row=0, column=1, sticky="ew")
        self.toolbar.grid_columnconfigure(12, weight=1)
        ctk.CTkButton(self.toolbar, text="SSH", width=65, command=self.connect_ssh_dialog).grid(row=0, column=0, padx=(12, 3), pady=10)
        ctk.CTkButton(self.toolbar, text="Telnet", width=65, fg_color="#2b5c8f", hover_color="#3875b5", command=self.connect_telnet_dialog).grid(row=0, column=1, padx=3, pady=10)
        ctk.CTkButton(self.toolbar, text="Serial", width=65, command=self.connect_serial_dialog).grid(row=0, column=2, padx=3, pady=10)
        ctk.CTkButton(self.toolbar, text="Disconnect", width=90, fg_color="#4a5563", command=self.disconnect_current).grid(row=0, column=3, padx=3, pady=10)
        ctk.CTkButton(self.toolbar, text="Logging", width=75, fg_color="#256d55", command=self.toggle_logging).grid(row=0, column=4, padx=3, pady=10)
        ctk.CTkButton(self.toolbar, text="Files", width=65, fg_color="#3a7d5c", hover_color="#4a9873", command=self.open_sftp_dialog).grid(row=0, column=5, padx=3, pady=10)
        ctk.CTkButton(self.toolbar, text="Help", width=70, fg_color="#b55328", hover_color="#d16232", command=lambda: SamplesDialog(self)).grid(row=0, column=6, padx=(12, 3), pady=10)
        ctk.CTkButton(self.toolbar, text="Run Script", width=80, fg_color="#7656b7", command=self.run_script).grid(row=0, column=7, padx=3, pady=10)
        ctk.CTkButton(self.toolbar, text="Multi-Script", width=90, fg_color="#8f3b76", hover_color="#a8478c", command=self.open_playlist_dialog).grid(row=0, column=8, padx=3, pady=10)
        ctk.CTkButton(self.toolbar, text="Clear", width=60, fg_color="#4a5563", command=self.clear_terminal).grid(row=0, column=9, padx=3, pady=10)
        ctk.CTkButton(self.toolbar, text="Profiles", width=70, fg_color="#4a5563", command=self.manage_profiles).grid(row=0, column=10, padx=3, pady=10)

        self.content = ctk.CTkFrame(self, fg_color="#02080d", corner_radius=0)
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)
        self.header_var = ctk.StringVar(value="No terminal")
        ctk.CTkLabel(self.content, textvariable=self.header_var, anchor="w", font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")
        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(self, textvariable=self.status_var, anchor="w", height=28).grid(row=2, column=1, sticky="ew", padx=8)

    def new_terminal(self):
        idx = len(self.sessions) + 1
        frame = ctk.CTkFrame(self.content, fg_color="#02080d", corner_radius=0)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        terminal = ctk.CTkTextbox(frame, fg_color=TERMINAL_BG, text_color=TERMINAL_FG, font=ctk.CTkFont(family="Consolas", size=14), wrap="none", corner_radius=8, border_width=1, border_color="#183248")
        terminal._textbox.configure(insertbackground=TERMINAL_ACCENT)
        terminal.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        session = TerminalSession(app=self, name=f"Terminal {idx}", frame=frame, terminal=terminal)
        self.bind_terminal_input(session)
        self.sessions.append(session)
        self.select_session(session)
        session.append("\r\n[New terminal. Use SSH, Telnet or Serial, then type directly here.]\r\n")
        session.render()
        self.refresh_session_list()
        self.after(150, lambda: self._apply_resize(session))

    def has_selection(self, session: TerminalSession) -> bool:
        try:
            return bool(session.terminal._textbox.index("sel.first"))
        except Exception:
            return False

    def bind_terminal_input(self, session: TerminalSession):
        t = session.terminal
        t.bind("<ButtonRelease-1>", lambda event, s=session: self.handle_terminal_click(s, event))
        t.bind("<KeyPress>", lambda event, s=session: self.handle_terminal_key(s, event))
        t.bind("<Button-3>", lambda event, s=session: self.show_context_menu(s, event))
        t.bind("<Configure>", lambda event, s=session: self.on_terminal_resize(s))
        t.bind("<MouseWheel>", lambda event, s=session: self.handle_mousewheel(s, event))
        t.bind("<Button-4>", lambda event, s=session: self.handle_mousewheel(s, event))
        t.bind("<Button-5>", lambda event, s=session: self.handle_mousewheel(s, event))

        if DND_AVAILABLE:
            try:
                t._textbox.drop_target_register(DND_FILES)
                t._textbox.dnd_bind("<<Drop>>", lambda event, s=session: self.handle_file_drop(s, event))
            except Exception:
                pass

    def compute_terminal_size(self, session: TerminalSession) -> tuple[int, int]:
        text_widget = session.terminal._textbox
        font = tkfont.Font(font=text_widget.cget("font"))
        char_width = max(font.measure("0"), 1)
        line_height = max(font.metrics("linespace"), 1)

        padding_px = 14
        widget_width = max(text_widget.winfo_width() - padding_px, char_width)
        widget_height = max(text_widget.winfo_height() - padding_px, line_height)

        cols = max(min(widget_width // char_width, 200), 20)
        rows = max(min(widget_height // line_height, 80), 5)
        return cols, rows

    def on_terminal_resize(self, session: TerminalSession):
        job = getattr(session, "_resize_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        session._resize_job = self.after(250, lambda: self._apply_resize(session))

    def _apply_resize(self, session: TerminalSession):
        session._resize_job = None
        try:
            cols, rows = self.compute_terminal_size(session)
            session.resize(cols, rows)
        except Exception:
            pass

    def handle_terminal_click(self, session: TerminalSession, event):
        self.select_session(session)
        if getattr(session, "alt_screen_active", False):
            return

        def enforce_active_line():
            try:
                if not session.terminal._textbox.tag_ranges("sel"):
                    last_line = session.terminal._textbox.index("end-1c").split(".")[0]
                    current_line = session.terminal._textbox.index("insert").split(".")[0]
                    if int(current_line) < int(last_line):
                        session.terminal._textbox.mark_set("insert", "end-1c")
            except Exception:
                pass
        self.after(10, enforce_active_line)

    def handle_mousewheel(self, session: TerminalSession, event) -> str:
        self.select_session(session)
        num = getattr(event, "num", None)
        if num == 4:
            lines = 3
        elif num == 5:
            lines = -3
        else:
            delta = getattr(event, "delta", 0)
            steps = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
            lines = steps * 3
        session.scroll_history(lines)
        return "break"

    def handle_terminal_key(self, session: TerminalSession, event) -> str:
        key = event.keysym
        ctrl = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)

        if session.scroll_offset and key not in (
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Prior", "Next",
        ):
            session.scroll_offset = 0
            session.render()

        if ctrl and shift and key.lower() == "c":
            self.copy_selection(session)
            return "break"

        if ctrl and shift and key.lower() == "x":
            self.cut_selection(session)
            return "break"

        if ctrl and shift and key.lower() == "v":
            self.paste_to_terminal(session)
            return "break"

        if shift and key == "Prior":
            session.scroll_history(session.rows - 2)
            return "break"
        if shift and key == "Next":
            session.scroll_history(-(session.rows - 2))
            return "break"

        if (ctrl and key in ("bracketright", "closebracket", "]")) or event.char == "\x1d":
            if session.connection and session.connection.label == "Telnet":
                session.close()
                session.append("\r\n[Telnet session disconnected via Ctrl + ] escape sequence]\r\n")
                session.render()
                self.refresh_session_list()
                return "break"

        if session.connection:
            if ctrl and not shift:
                key_lower = key.lower()

                if key_lower == "c" and self.has_selection(session):
                    self.copy_selection(session)
                    return "break"

                ctrl_map = {
                    "a": "\x01", "b": "\x02", "c": "\x03", "d": "\x04", "e": "\x05",
                    "f": "\x06", "g": "\x07", "h": "\x08", "i": "\x09", "j": "\x0a",
                    "k": "\x0b", "l": "\x0c", "m": "\x0d", "n": "\x0e", "o": "\x0f",
                    "p": "\x10", "q": "\x11", "r": "\x12", "s": "\x13", "t": "\x14",
                    "u": "\x15", "v": "\x16", "w": "\x17", "x": "\x18", "y": "\x19",
                    "z": "\x1a",
                }
                if key_lower in ctrl_map:
                    session.send(ctrl_map[key_lower])
                    return "break"

            if key in ("Left", "Right"):
                session.send("\x1b[D" if key == "Left" else "\x1b[C")
                return "break"
            if key in ("Up", "Down"):
                session.send("\x1b[A" if key == "Up" else "\x1b[B")
                return "break"

            if key == "BackSpace":
                cursor = session.screen.cursor
                if session.prompt_row == cursor.y and cursor.x <= session.prompt_col:
                    return "break"
                session.send("\x7f")
                return "break"

            if key == "Return":
                session.send("\r")
                session.awaiting_prompt = True
                return "break"

            special = {
                "Tab": "\t", "Escape": "\x1b",
                "Delete": "\x1b[3~", "Home": "\x1b[H", "End": "\x1b[F",
                "Prior": "\x1b[5~", "Next": "\x1b[6~",
            }
            if key in special:
                session.send(special[key])
                return "break"

            if event.char and len(event.char) == 1 and ord(event.char) >= 32:
                session.send(event.char)
                return "break"

            return "break"

        if ctrl and not shift and key.lower() == "c":
            if self.has_selection(session):
                self.copy_selection(session)
            return "break"

        if ctrl and not shift and key.lower() == "x":
            if self.has_selection(session):
                self.cut_selection(session)
            return "break"

        if ctrl and not shift and key.lower() == "v":
            self.paste_to_terminal(session)
            return "break"

        if key == "BackSpace":
            session.append("\b \b")
            session.render()
            return "break"

        if key == "Return":
            session.append("\r\n")
            session.render()
            return "break"

        if event.char and len(event.char) == 1 and ord(event.char) >= 32:
            session.append(event.char)
            session.render()
            return "break"

        return "break"

    def copy_selection(self, session: TerminalSession) -> str:
        try:
            self.clipboard_clear()
            self.clipboard_append(session.terminal._textbox.get("sel.first", "sel.last"))
        except Exception:
            pass
        return "break"

    def cut_selection(self, session: TerminalSession) -> str:
        try:
            self.clipboard_clear()
            text = session.terminal._textbox.get("sel.first", "sel.last")
            self.clipboard_append(text)
            if not session.connection:
                session.terminal._textbox.delete("sel.first", "sel.last")
        except Exception:
            pass
        return "break"

    def paste_to_terminal(self, session: TerminalSession) -> str:
        try:
            text = self.clipboard_get()
            if session.connection:
                session.send(text)
            else:
                session.append(text)
                session.render()
        except Exception:
            pass
        return "break"

    def show_context_menu(self, session: TerminalSession, event):
        self.select_session(session)
        has_sel = self.has_selection(session)

        menu = tk.Menu(
            self, tearoff=0,
            bg="#121a24", fg=TERMINAL_FG,
            activebackground="#2f6f95", activeforeground="#ffffff",
            relief="flat", bd=0,
        )
        menu.add_command(label="Copy", command=lambda: self.copy_selection(session), state="normal" if has_sel else "disabled")
        menu.add_command(label="Cut", command=lambda: self.cut_selection(session), state="normal" if has_sel else "disabled")
        menu.add_command(label="Paste", command=lambda: self.paste_to_terminal(session))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: self.select_all(session))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def select_all(self, session: TerminalSession) -> str:
        try:
            tb = session.terminal._textbox
            tb.tag_add("sel", "1.0", "end-1c")
            tb.mark_set("insert", "end-1c")
        except Exception:
            pass
        return "break"

    def select_session(self, session: TerminalSession):
        if self.active_session is session:
            return
        if self.active_session:
            try:
                if self.active_session.frame.winfo_exists() and self.active_session.frame.winfo_ismapped():
                    self.active_session.frame.grid_forget()
            except Exception:
                pass
        self.active_session = session
        session.frame.grid(row=1, column=0, sticky="nsew")
        self.header_var.set(self._status_text(session))
        session.terminal.focus_set()
        for row in self.session_list_widgets:
            try:
                if row.winfo_exists():
                    btn = row.winfo_children()[0]
                    row.configure(fg_color="#1c2936" if (btn.cget("text") == session.name) else "transparent")
            except Exception:
                pass

    def refresh_session_list(self):
        for w in self.session_list_widgets:
            try:
                if w.winfo_exists():
                    w.destroy()
            except Exception:
                pass
        self.session_list_widgets.clear()
        for idx, s in enumerate(self.sessions):
            row = ctk.CTkFrame(self.session_list, fg_color="#1c2936" if s is self.active_session else "transparent")
            row.grid(row=idx, column=0, padx=4, pady=4, sticky="ew")
            row.grid_columnconfigure(0, weight=1)
            self.session_list_widgets.append(row)
            btn = ctk.CTkButton(row, text=s.name, anchor="w", fg_color="transparent", hover_color="#24384a", command=lambda sess=s: self.select_session(sess))
            btn.bind("<Double-Button-1>", lambda e, sess=s: [self.select_session(sess), self.rename_terminal()])
            btn.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
            ctk.CTkButton(row, text="\u00d7", width=30, fg_color="#70303b", hover_color="#93404e", command=lambda sess=s: self.close_session(sess)).grid(row=0, column=1, padx=2, pady=2)

    def current_session(self) -> TerminalSession | None:
        return self.active_session

    def _status_text(self, s: TerminalSession) -> str:
        base = f"{s.name}  \u00b7  {s.connected_label}  \u00b7  Logging: {'ON' if s.log_enabled else 'OFF'}"
        if s.scroll_offset:
            base += f"  \u00b7  Scrollback ({s.scroll_offset} lines back)"
        return base

    def connect_ssh_dialog(self):
        s = self.current_session() or (self.new_terminal() or self.current_session())
        if not s:
            return
        d = SSHDialog(self)
        self.wait_window(d)
        if not d.result:
            return
        if d.result["save"]:
            pn = d.result["profile_name"] or f"{d.result['username']}@{d.result['host']}:{d.result['port']}"
            self.profile_store.upsert(pn, {"host": d.result["host"], "username": d.result["username"], "port": d.result["port"]})
        conn = SSHConnection(host=d.result["host"], username=d.result["username"], password=d.result["password"], port=d.result["port"], look_for_keys=not bool(d.result["password"]), allow_agent=not bool(d.result["password"]))
        self.connect_session(s, conn, f"SSH {d.result['host']}")

    def connect_serial_dialog(self):
        s = self.current_session() or (self.new_terminal() or self.current_session())
        if not s:
            return
        d = SerialDialog(self)
        self.wait_window(d)
        if d.result:
            self.connect_session(s, SerialConnection(d.result["port"], d.result["baud"]), f"Serial {d.result['port']} @ {d.result['baud']}")

    def connect_telnet_dialog(self):
        s = self.current_session() or (self.new_terminal() or self.current_session())
        if not s:
            return
        d = TelnetDialog(self)
        self.wait_window(d)
        if d.result:
            self.connect_session(s, TelnetConnection(d.result["host"], d.result["port"]), f"Telnet {d.result['host']}")

    def connect_session(self, s: TerminalSession, conn: BaseConnection, label: str):
        if s.connection:
            s.close()

        def worker():
            try:
                s.connection = conn
                conn.start(s.incoming)
                s.connected_label = label
                s.connection_lost_notified = False
                s.incoming.put(f"\r\n[Active: {label}]\r\n")
                s.awaiting_prompt = True
                self.after(300, lambda: self._apply_resize(s))
            except Exception as exc:
                error_text = str(exc)
                s.connection, s.connected_label = None, "Disconnected"
                s.incoming.put(f"\r\n[Connection failed: {error_text}]\r\n")
                self.after(0, lambda: self.select_session(s) if s in self.sessions else None)
                self.after(0, lambda: messagebox.showerror(
                    "Connection Failed",
                    f"Could not establish {label}.\n\n{error_text}",
                    parent=self,
                ))

        threading.Thread(target=worker, daemon=True).start()
        self.status_var.set(f"Connecting: {label}")
        self.after(200, lambda: self.select_session(s) if s in self.sessions else None)


    def disconnect_current(self):
        s = self.current_session()
        if s:
            s.close()
            s.append("\r\n[Disconnected]\r\n")
            s.render()
            self.select_session(s)

    def rename_terminal(self):
        s = self.current_session()
        if not s:
            return
        d = RenameDialog(self, s.name)
        self.wait_window(d)
        if d.result:
            s.name = d.result
            self.select_session(s)
            self.refresh_session_list()

    def close_current_terminal(self):
        if self.current_session():
            self.close_session(self.current_session())

    def close_session(self, s: TerminalSession):
        if not messagebox.askyesno("Close terminal", f"Close {s.name}?", parent=self):
            return
        s.close()
        if s in self.sessions:
            self.sessions.remove(s)
        if self.active_session is s:
            self.active_session = None
        try:
            if s.frame.winfo_exists():
                s.frame.grid_forget()
                s.frame.destroy()
        except Exception:
            pass
        if self.sessions:
            self.select_session(self.sessions[-1])
        else:
            self.header_var.set("No terminal")
        self.refresh_session_list()

    def toggle_logging(self):
        s = self.current_session()
        if not s:
            messagebox.showwarning("No Terminal", "Open terminal first.", parent=self)
            return
        if s.log_enabled:
            s.disable_logging()
            self.select_session(s)
        else:
            sn = re.sub(r"[^A-Za-z0-9_.-]+", "_", s.name).strip("_") or "terminal"
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            p = filedialog.asksaveasfilename(title="Save Log", initialdir=LOG_DIR, initialfile=f"{sn}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.log", filetypes=[("Logs", "*.log"), ("All", "*.*")], parent=self)
            if p:
                s.enable_custom_logging(Path(p))
                self.select_session(s)

    def open_playlist_dialog(self):
        if not self.sessions:
            self.new_terminal()
        MultiScriptDialog(self)

    def open_sftp_dialog(self):
        s = self.current_session()
        if not s or not s.connection or s.connection.label != "SSH":
            messagebox.showwarning("SSH required", "The Files browser requires an active SSH connection.", parent=self)
            return
        SFTPBrowserDialog(self, s)

    def handle_file_drop(self, session: TerminalSession, event):
        if not (session.connection and session.connection.label == "SSH"):
            messagebox.showwarning("SSH required", "Drag-and-drop upload requires an active SSH connection.", parent=self)
            return
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        paths = [p for p in paths if p]
        if not paths:
            return

        def worker():
            try:
                sftp = get_active_sftp(session)
                remote_home = sftp.normalize(".")
            except Exception as exc:
                session.incoming.put(f"\r\n[Upload failed: could not open SFTP session: {exc}]\r\n")
                return
            for local_path in paths:
                name = Path(local_path).name
                remote_path = posixpath.join(remote_home.rstrip("/") or "/", name)
                try:
                    session.incoming.put(f"\r\n[Uploading {name} -> {remote_path} ...]\r\n")
                    sftp.put(local_path, remote_path)
                    session.incoming.put(f"\r\n[Upload complete: {name}]\r\n")
                except Exception as exc:
                    session.incoming.put(f"\r\n[Upload failed for {name}: {exc}]\r\n")

        threading.Thread(target=worker, daemon=True).start()



    def clear_terminal(self):
        s = self.current_session()
        if s:
            s.terminal.delete("1.0", "end")
            s.clear_wait_buffer()

    def run_script(self):
        s = self.current_session()
        if not s:
            return
        p = filedialog.askopenfilename(title="Select Script", filetypes=[("Scripts", "*.ttl *.py"), ("All", "*.*")], parent=self)
        if p:
            threading.Thread(target=self._run_ttl if p.lower().endswith(".ttl") else self._run_python, args=(s, p), daemon=True).start()

    def _run_ttl(self, s: TerminalSession, p: str):
        try:
            s.incoming.put(f"\r\n[Running TTL: {p}]\r\n")
            TeraTermMacroRunner(self, s).run_file(p)
            s.incoming.put("\r\n[TTL completed]\r\n")
        except Exception as exc:
            s.incoming.put(f"\r\n[TTL error: {exc}]\r\n")

    def _run_python(self, s: TerminalSession, p: str):
        try:
            s.incoming.put(f"\r\n[Running Python: {p}]\r\n")
            execute_python_script_sync(s, p)
            s.incoming.put("\r\n[Python completed]\r\n")
        except Exception as exc:
            s.incoming.put(f"\r\n[Python error: {exc}]\r\n")

    def manage_profiles(self):
        win = ctk.CTkToplevel(self)
        win.title("SSH Profiles")
        win.geometry("540x360")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Saved SSH Profiles", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=18, pady=(16, 8))
        box = ctk.CTkScrollableFrame(win)
        box.pack(fill="both", expand=True, padx=16, pady=8)
        profile_widgets = []

        def ref():
            for w in profile_widgets:
                try:
                    if w.winfo_exists():
                        w.destroy()
                except Exception:
                    pass
            profile_widgets.clear()
            for idx, (n, pf) in enumerate(sorted(self.profile_store.profiles.items())):
                r = ctk.CTkFrame(box)
                r.grid(row=idx, column=0, sticky="ew", padx=6, pady=4)
                r.grid_columnconfigure(0, weight=1)
                profile_widgets.append(r)
                ctk.CTkLabel(r, text=f"{n} ({pf.get('username','')}@{pf.get('host','')})", anchor="w").grid(row=0, column=0, padx=10, pady=8)
                ctk.CTkButton(r, text="Delete", width=70, fg_color="#8a2d3b", command=lambda name=n: [self.profile_store.delete(name), ref()]).grid(row=0, column=1, padx=8)

        ref()
        ctk.CTkButton(win, text="Close", command=win.destroy).pack(padx=16, pady=12, anchor="e")

    def poll_queues(self):
        for s in list(self.sessions):
            try:
                if not s.frame.winfo_exists():
                    continue
            except Exception:
                continue

            got_data = False
            while True:
                try:
                    data = s.incoming.get_nowait()
                except queue.Empty:
                    break
                got_data = True
                try:
                    s.append(data)
                except Exception as exc:
                    print(f"[append() error on '{s.name}']: {exc}", file=sys.stderr)

            if got_data:
                try:
                    s.render()
                except Exception as exc:
                    print(f"[render() error on '{s.name}']: {exc}", file=sys.stderr)

                if s.awaiting_prompt:
                    s.prompt_row = s.screen.cursor.y
                    s.prompt_col = s.screen.cursor.x
                    s.awaiting_prompt = False

            if s is self.active_session:
                self.header_var.set(self._status_text(s))

        self.after(40, self.poll_queues)

    def on_close(self):
        for s in list(self.sessions):
            s.close()
        self.destroy()

def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    app = TerminalApp()
    app.mainloop()

if __name__ == "__main__":
    main()
