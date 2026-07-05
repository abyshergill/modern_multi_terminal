from __future__ import annotations
import stat
import threading
from pathlib import Path
import posixpath
import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.sftp_hops import get_hops, add_jump_hop, get_active_sftp, remove_last_hop

class AddHopDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Add Jump Hop")
        self.geometry("380x300")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Tunnel to Next Server", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 10), sticky="w")

        self.host = ctk.StringVar()
        self.port = ctk.StringVar(value="22")
        self.username = ctk.StringVar()
        self.password = ctk.StringVar()

        rows = [("Host/IP", self.host, False), ("Port", self.port, False), ("Username", self.username, False), ("Password", self.password, True)]
        for idx, (label, var, secret) in enumerate(rows, start=1):
            ctk.CTkLabel(self, text=label).grid(row=idx, column=0, padx=(16, 8), pady=6, sticky="w")
            ctk.CTkEntry(self, textvariable=var, show="*" if secret else None).grid(row=idx, column=1, padx=16, pady=6, sticky="ew")

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=6, column=0, columnspan=2, padx=16, pady=18, sticky="ew")
        btns.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(btns, text="Cancel", fg_color="#3a3f45", command=self.destroy).grid(row=0, column=0, padx=5, sticky="ew")
        ctk.CTkButton(btns, text="Connect", command=self._ok).grid(row=0, column=1, padx=5, sticky="ew")

    def _ok(self):
        if not self.host.get().strip():
            messagebox.showerror("Missing host", "Enter the host/IP for this hop.", parent=self)
            return
        try:
            port = int(self.port.get() or "22")
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be numeric.", parent=self)
            return
        self.result = {
            "host": self.host.get().strip(),
            "port": port,
            "username": self.username.get().strip(),
            "password": self.password.get(),
        }
        self.destroy()

class SFTPBrowserDialog(ctk.CTkToplevel):
    def __init__(self, app, session):
        super().__init__(app)
        self.app = app
        self.session = session
        self.title(f"Remote Files \u2014 {session.name}")
        self.geometry("760x520")
        self.transient(app)

        self.current_path = "."
        self.row_widgets = []
        self.selected_entry = None
        self._nav_token = 0

        self._build_ui()
        self._init_hops_and_list()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        hop_bar = ctk.CTkFrame(self, fg_color="transparent")
        hop_bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 4))
        hop_bar.grid_columnconfigure(0, weight=1)

        self.hop_var = ctk.StringVar(value="Connecting...")
        self.hop_menu = ctk.CTkOptionMenu(hop_bar, variable=self.hop_var, values=["Connecting..."], command=self._on_hop_selected)
        self.hop_menu.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(hop_bar, text="+ Add Jump Hop", width=130, fg_color="#7656b7", command=self._add_hop_dialog).grid(row=0, column=1, padx=3)
        ctk.CTkButton(hop_bar, text="Remove Last Hop", width=130, fg_color="#8a2d3b", command=self._remove_hop).grid(row=0, column=2, padx=3)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))
        top.grid_columnconfigure(0, weight=1)

        self.path_var = ctk.StringVar(value="")
        self.path_entry = ctk.CTkEntry(top, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.path_entry.bind("<Return>", lambda e: self._navigate_to(self.path_var.get()))

        ctk.CTkButton(top, text="Go", width=50, command=lambda: self._navigate_to(self.path_var.get())).grid(row=0, column=1, padx=3)
        ctk.CTkButton(top, text="Up", width=50, command=self._go_up).grid(row=0, column=2, padx=3)
        ctk.CTkButton(top, text="Refresh", width=70, command=self._refresh).grid(row=0, column=3, padx=3)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=14)
        ctk.CTkButton(actions, text="Upload File...", width=120, fg_color="#2f6f95", command=self._upload_dialog).pack(side="left", padx=(0, 6))
        ctk.CTkButton(actions, text="Download Selected", width=140, fg_color="#256d55", command=self._download_selected).pack(side="left", padx=6)
        ctk.CTkButton(actions, text="Delete Selected", width=120, fg_color="#8a2d3b", command=self._delete_selected).pack(side="left", padx=6)

        self.list_frame = ctk.CTkScrollableFrame(self, label_text="Remote directory")
        self.list_frame.grid(row=3, column=0, sticky="nsew", padx=14, pady=(6, 6))
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.status_var = ctk.StringVar(value="")
        ctk.CTkLabel(self, textvariable=self.status_var, anchor="w", text_color="#7b8b99").grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 12))

    def _set_status(self, text):
        try:
            self.status_var.set(text)
        except Exception:
            pass

    def _refresh_hop_menu(self):
        hops = self.session.sftp_hops
        labels = [h["label"] for h in hops]
        self.hop_menu.configure(values=labels)
        if labels:
            self.hop_var.set(labels[self.session.active_hop_index])

    def _init_hops_and_list(self):
        def worker():
            try:
                get_hops(self.session)
                self.after(0, self._refresh_hop_menu)
                sftp = get_active_sftp(self.session)
                home = sftp.normalize(".")
                self.current_path = home
                self.after(0, self._refresh)
            except Exception as exc:
                self.after(0, lambda: self._set_status(f"SFTP connect failed: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_hop_selected(self, label):
        hops = self.session.sftp_hops
        for idx, h in enumerate(hops):
            if h["label"] == label:
                self.session.active_hop_index = idx
                break
        self._set_status(f"Switched to {label}")

        def worker():
            try:
                sftp = get_active_sftp(self.session)
                home = sftp.normalize(".")
                self.current_path = home
                self.after(0, self._refresh)
            except Exception as exc:
                self.after(0, lambda: self._set_status(f"Failed to switch hop: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _add_hop_dialog(self):
        d = AddHopDialog(self)
        self.wait_window(d)
        if not d.result:
            return
        self._set_status(f"Tunneling to {d.result['host']}...")

        def worker():
            try:
                add_jump_hop(self.session, d.result["host"], d.result["port"], d.result["username"], d.result["password"])
                self.after(0, self._refresh_hop_menu)
                sftp = get_active_sftp(self.session)
                home = sftp.normalize(".")
                self.current_path = home
                self.after(0, self._refresh)
            except Exception as exc:
                error_text = str(exc)
                self.after(0, lambda: self._set_status(f"Jump hop failed: {error_text}"))
                self.after(0, lambda: messagebox.showerror(
                    "Jump Hop Connection Failed",
                    f"Could not connect to {d.result['host']}:{d.result['port']}.\n\n{error_text}",
                    parent=self,
                ))
        threading.Thread(target=worker, daemon=True).start()


    def _remove_hop(self):
        if len(self.session.sftp_hops) <= 1:
            self._set_status("Only one hop remains; nothing to remove.")
            return
        remove_last_hop(self.session)
        self._refresh_hop_menu()

        def worker():
            try:
                sftp = get_active_sftp(self.session)
                home = sftp.normalize(".")
                self.current_path = home
                self.after(0, self._refresh)
            except Exception as exc:
                self.after(0, lambda: self._set_status(f"Failed to reload after removing hop: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _navigate_to(self, path):
        self.current_path = path.strip() or "."
        self._refresh()

    def _go_up(self):
        parent = posixpath.dirname(self.current_path.rstrip("/")) or "/"
        self.current_path = parent
        self._refresh()


    def _refresh(self):
        self._nav_token += 1
        token = self._nav_token
        target_path = self.current_path
        self._set_status("Loading...")

        def worker():
            try:
                sftp = get_active_sftp(self.session)
                raw_entries = sftp.listdir_attr(target_path)
                resolved = []
                for entry in raw_entries:
                    is_dir = stat.S_ISDIR(entry.st_mode)
                    is_link = stat.S_ISLNK(entry.st_mode)
                    if is_link:
                        full_path = posixpath.join(target_path.rstrip("/") or "/", entry.filename)
                        try:
                            target_stat = sftp.stat(full_path)
                            is_dir = stat.S_ISDIR(target_stat.st_mode)
                        except Exception:
                            is_dir = False
                    resolved.append((entry, is_dir))
                resolved.sort(key=lambda pair: (not pair[1], pair[0].filename.lower()))
                self.after(0, lambda: self._apply_refresh_result(token, target_path, resolved, None))
            except Exception as exc:
                error_text = str(exc)
                self.after(0, lambda: self._apply_refresh_result(token, target_path, [], error_text))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_refresh_result(self, token, path, resolved, error):
        if token != self._nav_token:
            # A newer navigation request has already superseded this one; discard.
            return
        self.current_path = path
        self._populate(resolved, error=error)



    def _populate(self, resolved_entries, error=None):
        self.path_var.set(self.current_path)
        for w in self.row_widgets:
            try:
                if w.winfo_exists():
                    w.destroy()
            except Exception:
                pass
        self.row_widgets.clear()
        self.selected_entry = None

        if error:
            err_row = ctk.CTkLabel(self.list_frame, text=f"\u26a0  Failed to open this folder: {error}", text_color="#e05561", anchor="w")
            err_row.pack(fill="x", pady=8, padx=4)
            self.row_widgets.append(err_row)
            self._set_status("Error loading directory")
            return

        if not resolved_entries:
            empty_row = ctk.CTkLabel(self.list_frame, text="(this folder is empty)", text_color="#7b8b99", anchor="w")
            empty_row.pack(fill="x", pady=8, padx=4)
            self.row_widgets.append(empty_row)
            self._set_status("0 items")
            return

        for entry, is_dir in resolved_entries:
            icon = "\U0001F4C1" if is_dir else "\U0001F4C4"
            size = "" if is_dir else f"{entry.st_size:,} bytes"

            row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            row.grid_columnconfigure(0, weight=1)

            label = ctk.CTkLabel(row, text=f"{icon}  {entry.filename}", anchor="w")
            label.grid(row=0, column=0, sticky="ew", padx=4, pady=3)
            size_label = ctk.CTkLabel(row, text=size, text_color="#7b8b99", width=110, anchor="e")
            size_label.grid(row=0, column=1, padx=6)

            entry_data = {"name": entry.filename, "is_dir": is_dir}

            def on_click(e=None, data=entry_data, r=row):
                self._select_row(data, r)

            def on_double(e=None, data=entry_data):
                if data["is_dir"]:
                    self.current_path = posixpath.join(self.current_path.rstrip("/") or "/", data["name"])
                    self._refresh()

            label.bind("<Button-1>", on_click)
            size_label.bind("<Button-1>", on_click)
            label.bind("<Double-Button-1>", on_double)
            size_label.bind("<Double-Button-1>", on_double)

            self.row_widgets.append(row)

        self._set_status(f"{len(resolved_entries)} items")


    def _select_row(self, data, row):
        for w in self.row_widgets:
            try:
                w.configure(fg_color="transparent")
            except Exception:
                pass
        row.configure(fg_color="#1c2936")
        self.selected_entry = data

    def _upload_dialog(self):
        paths = filedialog.askopenfilenames(title="Select file(s) to upload", parent=self)
        if paths:
            self._upload_paths(list(paths))

    def _upload_paths(self, local_paths):
        target_dir = self.current_path

        def worker():
            try:
                sftp = get_active_sftp(self.session)
            except Exception as exc:
                self.after(0, lambda: self._set_status(f"SFTP unavailable: {exc}"))
                return
            for lp in local_paths:
                name = Path(lp).name
                remote_path = posixpath.join(target_dir.rstrip("/") or "/", name)
                try:
                    self.after(0, lambda n=name: self._set_status(f"Uploading {n}..."))
                    sftp.put(lp, remote_path)
                except Exception as exc:
                    self.after(0, lambda n=name, e=exc: self._set_status(f"Failed to upload {n}: {e}"))
                    return
            self.after(0, lambda: self._set_status("Upload complete"))
            self.after(0, self._refresh)
        threading.Thread(target=worker, daemon=True).start()

    def _download_selected(self):
        if not self.selected_entry or self.selected_entry["is_dir"]:
            messagebox.showwarning("No file selected", "Select a remote file (not a folder) to download.", parent=self)
            return
        name = self.selected_entry["name"]
        local_path = filedialog.asksaveasfilename(title="Save file as", initialfile=name, parent=self)
        if not local_path:
            return
        remote_path = posixpath.join(self.current_path.rstrip("/") or "/", name)

        def worker():
            try:
                self.after(0, lambda: self._set_status(f"Downloading {name}..."))
                sftp = get_active_sftp(self.session)
                sftp.get(remote_path, local_path)
                self.after(0, lambda: self._set_status(f"Downloaded {name} -> {local_path}"))
            except Exception as exc:
                self.after(0, lambda: self._set_status(f"Download failed: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _delete_selected(self):
        if not self.selected_entry:
            return
        if self.selected_entry["is_dir"]:
            messagebox.showwarning("Not supported", "Folder deletion is not supported here.", parent=self)
            return
        name = self.selected_entry["name"]
        if not messagebox.askyesno("Delete file", f"Delete remote file '{name}'?", parent=self):
            return
        remote_path = posixpath.join(self.current_path.rstrip("/") or "/", name)
        def worker():
            try:
                sftp = get_active_sftp(self.session)
                sftp.remove(remote_path)
                self.after(0, lambda: self._set_status(f"Deleted {name}"))
                self.after(0, self._refresh)
            except Exception as exc:
                self.after(0, lambda: self._set_status(f"Delete failed: {exc}"))
        threading.Thread(target=worker, daemon=True).start()
