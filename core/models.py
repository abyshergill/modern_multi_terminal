from __future__ import annotations
import queue
import re
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import TerminalApp
    from core.connections import BaseConnection

@dataclass
class TerminalSession:
    app: "TerminalApp"
    name: str
    frame: object
    terminal: object
    incoming: queue.Queue[str] = field(default_factory=queue.Queue)
    connection: "BaseConnection" | None = None
    connected_label: str = "Disconnected"
    log_enabled: bool = False
    log_file: object | None = None
    recv_buffer: str = ""
    recv_condition: threading.Condition = field(default_factory=threading.Condition)

    def append(self, data: str) -> None:
        try:
            if not self.terminal.winfo_exists():
                return
        except Exception:
            return

        # ─── UPGRADE: ADVANCED ANSI CLEANER (VAPORIZES [!p GARBAGE) ───
        data = re.sub(r'\x1b\].*?(?:\x07|\x1b\\)', '', data)
        data = data.replace('\x07', '')  # Remove Linux audio bell
        data = re.sub(r'\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]', '', data) 
        # ───────────────────────────────────────────────────────────────

        for char in data:
            if char in ("\x08", "\x7f"):
                if self.terminal.compare("insert", ">", "1.0"):
                    self.terminal.delete("insert - 1c")
            elif char == "\r":
                continue
            else:
                self.terminal.insert("insert", char)

        self.terminal.see("insert")

    def send(self, data: str) -> None:
        if not self.connection:
            self.append("[No active connection]\n")
            return
        try:
            self.connection.send(data)
            if self.log_enabled and self.log_file:
                self.log_file.write(data); self.log_file.flush()
        except Exception as exc:
            self.append(f"[Send error: {exc}]\n")
    
    def wait_for(self, pattern: str, timeout: float = 60.0, case_sensitive: bool = True) -> bool:
        deadline = time.time() + timeout
        needle = pattern if case_sensitive else pattern.lower()
        with self.recv_condition:
            while True:
                haystack = self.recv_buffer if case_sensitive else self.recv_buffer.lower()
                if needle in haystack:
                    return True
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self.recv_condition.wait(min(0.2, remaining))

    def clear_wait_buffer(self) -> None:
        with self.recv_condition: self.recv_buffer = ""

    def enable_custom_logging(self, file_path: Path) -> None:
        if self.log_enabled: return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = file_path.open("a", encoding="utf-8", errors="replace")
        self.log_enabled = True
        self.append(f"\n[Logging started -> {file_path}]\n")

    def disable_logging(self) -> None:
        was_enabled = self.log_enabled
        self.log_enabled = False
        try:
            if self.log_file: self.log_file.close()
        finally: self.log_file = None
        if was_enabled:
            try:
                if self.terminal.winfo_exists(): self.append("\n[Logging stopped]\n")
            except Exception: pass

    def close(self) -> None:
        try:
            if self.connection: self.connection.close()
        finally:
            self.connection = None
            self.connected_label = "Disconnected"
            self.disable_logging()

@dataclass(eq=False)
class PlaylistItem:
    path: str
    timeout: float
    target_session: TerminalSession
    status: str = "Pending"