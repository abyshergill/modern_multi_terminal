from __future__ import annotations
import re
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from core.models import PlaylistItem
from core.script_engine import TeraTermMacroRunner, execute_python_script_sync
from gui.dialogs import OperatorGateDialog

TERMINAL_ACCENT = "#46f0a6"
TERMINAL_MUTED = "#7b8b99"

def trigger_os_beep():
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception: print("\a", end="", file=sys.stderr)

class PlaylistSupervisorThread(threading.Thread):
    def __init__(self, app: object, playlist: list[PlaylistItem], beep_on_alert: bool, ui_callback: object, on_finish_callback: object):
        super().__init__(daemon=True)
        self.app, self.playlist, self.beep, self.ui_callback, self.on_finish_callback, self.stopped = app, playlist, beep_on_alert, ui_callback, on_finish_callback, False

    def run(self):
        for idx, item in enumerate(self.playlist):
            if self.stopped: break
            sess = item.target_session
            if sess not in self.app.sessions:
                sess = self.app.sessions[0] if self.app.sessions else None
                if not sess: break

            self.app.after(0, lambda s=sess: self.app.select_session(s) if s in self.app.sessions else None)
            sess.incoming.put(f"\r\n[═══ PLAYLIST STEP ({idx+1}/{len(self.playlist)}) ═══]\r\n")
            item.status = "Running"; self._push_ui()
            sess.incoming.put(f"[Playlist ➔] Executing: {Path(item.path).name}\n")

            start_marker, code_failed, error_reason = len(sess.recv_buffer), False, ""
            try:
                if item.path.lower().endswith(".ttl"): TeraTermMacroRunner(self.app, sess).run_file(item.path)
                else: execute_python_script_sync(sess, item.path)
            except Exception as e: code_failed, error_reason = True, f"Script Exception: {e}"

            current_timeout, passed = item.timeout, False
            while not passed and not self.stopped:
                if code_failed: choice = self._spawn_gate(sess, item, error_reason, start_marker)
                else:
                    deadline, detected = time.time() + current_timeout, False
                    while time.time() < deadline:
                        if self.stopped: break
                        time.sleep(0.1)
                        item.status = f"Sniffing ({max(0.0, deadline - time.time()):.1f}s)"; self._push_ui()
                        if re.search(r'[\$#>\]]\s*$', sess.recv_buffer[start_marker:]): detected = True; break
                    if detected: passed, item.status = True, "Passed"; self._push_ui(); sess.incoming.put(f"[Playlist ✔] Hand-off verified for {Path(item.path).name}\n"); break
                    else: choice = self._spawn_gate(sess, item, f"Deadline expired ({current_timeout}s) without prompt.", start_marker)

                if choice == "EXTEND": code_failed, current_timeout = False, 15.0; sess.incoming.put("[Playlist ➔] Extension granted...\n")
                elif choice == "FORCE": passed, item.status = True, "Passed (Forced)"; self._push_ui(); sess.incoming.put("[Playlist ⚠️] Forced progression.\n")
                else: item.status, self.stopped = "Aborted", True; self._push_ui(); sess.incoming.put("[Playlist 🛑] Aborted.\n"); break

        if not self.stopped:
            names = "\n".join(f"✔   {Path(item.path).name}   [on {item.target_session.name}]" for item in self.playlist)
            self.app.after(0, lambda: self.on_finish_callback(f"All {len(self.playlist)} scripts ran successfully:\n\n{names}"))

    def _spawn_gate(self, sess: object, item: PlaylistItem, reason: str, buf_start: int) -> str:
        item.status = "GATE TRIGGERED"; self._push_ui()
        if self.beep: trigger_os_beep()
        tail = sess.recv_buffer[buf_start:][-250:]
        lock, holder = threading.Event(), {"choice": "ABORT"}
        self.app.after(0, lambda: OperatorGateDialog(self.app, item.path, reason, tail, lock, holder))
        lock.wait()
        return holder["choice"]

    def _push_ui(self): self.app.after(0, self.ui_callback)

class MultiScriptDialog(ctk.CTkToplevel):
    def __init__(self, app: object):
        super().__init__(app)
        self.app, self.playlist, self.supervisor, self.live_status_labels, self.row_widgets = app, [], None, {}, []
        self.title("DevOps Suite DAW Manager"); self.geometry("880x520"); self.transient(app); self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent"); header.grid(row=0, column=0, padx=20, pady=(16, 8), sticky="ew")
        ctk.CTkLabel(header, text="Multi-Script DAW Suite", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        self.beep_var = ctk.BooleanVar(value=True); ctk.CTkCheckBox(header, text="Audio chime on Human Gate", variable=self.beep_var).pack(side="right")
        self.scroll = ctk.CTkScrollableFrame(self, label_text="Queued Scripts & Target Routing"); self.scroll.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")
        toolbar = ctk.CTkFrame(self, fg_color="transparent"); toolbar.grid(row=2, column=0, padx=20, pady=16, sticky="ew"); toolbar.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(toolbar, text="+ Add Script Files", fg_color="#2f6f95", command=self._add_files).grid(row=0, column=0, sticky="w")
        self.launch_btn = ctk.CTkButton(toolbar, text="Launch Full Suite", width=150, fg_color="#256d55", hover_color="#2f8a6c", command=self._launch_all); self.launch_btn.grid(row=0, column=1, sticky="e")
        self._rebuild_grid()

    def _add_files(self):
        default_sess = self.app.active_session if (self.app.active_session in self.app.sessions) else self.app.sessions[0]
        for p in filedialog.askopenfilenames(title="Select Scripts", filetypes=[("Scripts", "*.ttl *.py"), ("All", "*.*")], parent=self):
            self.playlist.append(PlaylistItem(path=p, timeout=15.0, target_session=default_sess))
        self._rebuild_grid()

    def _update_live_ui(self):
        colors = {"Pending": TERMINAL_MUTED, "Running": "#ffd54f", "Passed": TERMINAL_ACCENT, "GATE": "#ff5722"}
        for item, lbl in self.live_status_labels.items():
            try:
                if lbl.winfo_exists(): lbl.configure(text=item.status, text_color=colors.get(item.status.split("(")[0].strip(), "#d8f3dc"))
            except Exception: pass

    def _rebuild_grid(self):
        for w in self.row_widgets:
            try:
                if w.winfo_exists(): w.destroy()
            except Exception: pass
        self.row_widgets.clear(); self.live_status_labels.clear()
        if not self.playlist:
            empty_lbl = ctk.CTkLabel(self.scroll, text="[ Suite is empty. Click '+ Add Script Files' below. ]", text_color=TERMINAL_MUTED); empty_lbl.pack(pady=40)
            self.row_widgets.append(empty_lbl); self.launch_btn.configure(state="disabled"); return

        self.launch_btn.configure(state="normal" if not self.supervisor or not self.supervisor.is_alive() else "disabled")
        session_names = [s.name for s in self.app.sessions]
        for idx, item in enumerate(self.playlist):
            row = ctk.CTkFrame(self.scroll, fg_color="#121a24"); row.pack(fill="x", pady=4, padx=4); row.grid_columnconfigure(1, weight=1); self.row_widgets.append(row)
            ctk.CTkLabel(row, text=f"{idx+1}.", font=ctk.CTkFont(weight="bold"), width=24).grid(row=0, column=0, padx=(6, 2), pady=10)
            ctk.CTkLabel(row, text=Path(item.path).name, anchor="w", font=ctk.CTkFont(family="Consolas")).grid(row=0, column=1, sticky="ew", pady=10)
            opt = ctk.CTkOptionMenu(row, values=session_names, width=115, command=lambda val, i=item: self._route_session(i, val))
            opt.set(item.target_session.name if item.target_session in self.app.sessions else session_names[0]); opt.grid(row=0, column=2, padx=6)
            ctk.CTkLabel(row, text="Wait:").grid(row=0, column=3, padx=(2, 1))
            t_entry = ctk.CTkEntry(row, width=45); t_entry.grid(row=0, column=4, padx=1); t_entry.insert(0, str(int(item.timeout)))
            t_entry.bind("<KeyRelease>", lambda e, i=item, w=t_entry: self._update_t(i, w)); ctk.CTkLabel(row, text="s").grid(row=0, column=5, padx=(0, 6))
            lbl_status = ctk.CTkLabel(row, text=item.status, width=110); lbl_status.grid(row=0, column=6, padx=4); self.live_status_labels[item] = lbl_status
            ctrls = ctk.CTkFrame(row, fg_color="transparent"); ctrls.grid(row=0, column=7, padx=4)
            ctk.CTkButton(ctrls, text="▲", width=24, command=lambda i=idx: self._swap(i, i-1)).pack(side="left", padx=1)
            ctk.CTkButton(ctrls, text="▼", width=24, command=lambda i=idx: self._swap(i, i+1)).pack(side="left", padx=1)
            ctk.CTkButton(ctrls, text="► Single", width=60, fg_color="#2f6f95", hover_color="#3d8bb8", command=lambda i=item: self._run_single(i)).pack(side="left", padx=4)
            ctk.CTkButton(ctrls, text="×", width=24, fg_color="#8a2d3b", command=lambda i=item: self._rm(i)).pack(side="left", padx=1)
        self._update_live_ui()

    def _route_session(self, item: PlaylistItem, name: str):
        for s in self.app.sessions:
            if s.name == name: item.target_session = s; break
    def _update_t(self, item: PlaylistItem, w: object):
        try: item.timeout = float(w.get() or 15.0)
        except ValueError: pass
    def _swap(self, i1: int, i2: int):
        if 0 <= i1 < len(self.playlist) and 0 <= i2 < len(self.playlist): self.playlist[i1], self.playlist[i2] = self.playlist[i2], self.playlist[i1]; self._rebuild_grid()
    def _rm(self, item: PlaylistItem):
        if item in self.playlist: self.playlist.remove(item)
        self._rebuild_grid()
    def _on_suite_success(self, summary: str):
        try: self.destroy()
        except Exception: pass
        messagebox.showinfo("Suite Completed", summary)
    def _run_single(self, item: PlaylistItem):
        if self.supervisor and self.supervisor.is_alive(): return
        self.supervisor = PlaylistSupervisorThread(self.app, [item], self.beep_var.get(), self._update_live_ui, lambda msg: messagebox.showinfo("Single Passed", msg)); self.supervisor.start()
    def _launch_all(self):
        self.supervisor = PlaylistSupervisorThread(self.app, self.playlist, self.beep_var.get(), self._update_live_ui, self._on_suite_success); self.supervisor.start(); self._update_live_ui()