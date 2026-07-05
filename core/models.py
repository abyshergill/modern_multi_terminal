from __future__ import annotations
import queue
import threading
import time
import tkinter.font as tkfont
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pyte

from core.theme import TERMINAL_BG, TERMINAL_FG, TERMINAL_ACCENT, PALETTE

if TYPE_CHECKING:
    from main import TerminalApp
    from core.connections import BaseConnection

DEFAULT_COLS = 80
DEFAULT_ROWS = 24

# PALETTE = {
#     "black": "#1c1c1c", "red": "#e05561", "green": "#8cc265",
#     "brown": "#d2b967", "blue": "#4aa5f0", "magenta": "#c162de",
#     "cyan": "#42c7b8", "white": "#d8f3dc",
# }

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
    cols: int = DEFAULT_COLS
    rows: int = DEFAULT_ROWS
    awaiting_prompt: bool = False
    prompt_row: int = -1
    prompt_col: int = 0
    scroll_offset: int = 0
    connection_lost_notified: bool = False
    sftp_hops: list = field(default_factory=list)
    active_hop_index: int = 0

    def __post_init__(self):
        self.screen = pyte.HistoryScreen(self.cols, self.rows, history=5000, ratio=0.5)
        self.stream = pyte.Stream(self.screen)
        self._tags_ready = False
        self._known_fg_tags: set[str] = set()

    @property
    def alt_screen_active(self) -> bool:
        try:
            mode = self.screen.mode
            return any(m in mode for m in (1049, 47, 1047))
        except Exception:
            return False

    def resize(self, cols: int, rows: int) -> None:
        cols = max(cols, 20)
        rows = max(rows, 5)
        if cols == self.cols and rows == self.rows:
            return
        self.cols, self.rows = cols, rows
        try:
            self.screen.resize(rows, cols)
        except Exception:
            pass
        if self.connection:
            try:
                self.connection.resize(cols, rows)
            except Exception:
                pass
        self.render()

    def scroll_history(self, delta_lines: int) -> None:
        """Positive delta_lines scrolls back into older output,
        negative delta_lines scrolls forward toward the live tail.
        Reads pyte's captured scrollback without mutating the live screen."""
        try:
            max_offset = len(self.screen.history.top)
        except Exception:
            max_offset = 0
        self.scroll_offset = max(0, min(self.scroll_offset + delta_lines, max_offset))
        self.render()

    def snap_to_live(self) -> None:
        if self.scroll_offset:
            self.scroll_offset = 0
            self.render()


    def append(self, data: str) -> None:
        """Feed remote/local bytes into the pyte VT100 emulator.
        Does NOT touch the widget directly -- call render() after this."""
        try:
            if not self.terminal.winfo_exists():
                return
        except Exception:
            return

        try:
            self.stream.feed(data)
        except Exception:
            pass

        with self.recv_condition:
            self.recv_buffer += data
            if len(self.recv_buffer) > 250_000:
                self.recv_buffer = self.recv_buffer[-125_000:]
            self.recv_condition.notify_all()

        if self.log_enabled and self.log_file:
            try:
                self.log_file.write(data)
                self.log_file.flush()
            except Exception:
                pass

    def _setup_tags(self, text_widget) -> None:
        base_font = tkfont.Font(font=text_widget.cget("font"))
        bold_font = (base_font.actual("family"), base_font.actual("size"), "bold")

        text_widget.tag_configure("reverse", foreground=TERMINAL_BG, background=TERMINAL_FG)
        text_widget.tag_configure("bold", font=bold_font)

        for name, color in PALETTE.items():
            tag = f"fg_{name}"
            text_widget.tag_configure(tag, foreground=color)
            self._known_fg_tags.add(tag)

    def _tag_for_char(self, char):
        if getattr(char, "reverse", False):
            return "reverse"
        fg = getattr(char, "fg", "default")
        if fg and fg != "default":
            candidate = f"fg_{fg}"
            if candidate in self._known_fg_tags:
                return candidate
        if getattr(char, "bold", False):
            return "bold"
        return None

    def render(self) -> None:
        """Redraw the terminal widget from the current scroll window.
        When scroll_offset is 0, shows the live screen. When > 0, shows a
        historical window built from pyte's captured scrollback lines,
        without ever mutating the live screen buffer."""
        try:
            if not self.terminal.winfo_exists():
                return
        except Exception:
            return

        text_widget = self.terminal._textbox

        if not self._tags_ready:
            self._setup_tags(text_widget)
            self._tags_ready = True

        screen = self.screen
        rows = screen.lines
        cols = screen.columns

        if self.scroll_offset > 0:
            history = list(screen.history.top)
            total_history = len(history)
            k = min(self.scroll_offset, total_history)
            start = total_history - k
            end = min(total_history, start + rows)
            from_history = history[start:end]
            remaining = rows - len(from_history)
            from_buffer = [screen.buffer[y] for y in range(remaining)] if remaining > 0 else []
            display_rows = from_history + from_buffer
        else:
            display_rows = [screen.buffer[y] for y in range(rows)]

        text_widget.delete("1.0", "end")

        for row in display_rows:
            run_text = ""
            run_tag = None
            for x in range(cols):
                char = row[x]
                tag = self._tag_for_char(char)
                ch = char.data or " "
                if tag != run_tag:
                    if run_text:
                        text_widget.insert("end", run_text, run_tag or ())
                    run_text = ch
                    run_tag = tag
                else:
                    run_text += ch
            if run_text:
                text_widget.insert("end", run_text, run_tag or ())
            text_widget.insert("end", "\n")

        if self.scroll_offset == 0:
            cursor_row = min(screen.cursor.y + 1, rows)
            cursor_col = min(screen.cursor.x, max(cols - 1, 0))
            try:
                text_widget.mark_set("insert", f"{cursor_row}.{cursor_col}")
            except Exception:
                pass
            text_widget.see("end")


    def send(self, data: str) -> None:
        if not self.connection:
            if not self.connection_lost_notified:
                self.append("\r\n[No active connection]\r\n")
                self.render()
                self.connection_lost_notified = True
            return
        try:
            self.connection.send(data)
            if self.log_enabled and self.log_file:
                self.log_file.write(data)
                self.log_file.flush()
        except Exception as exc:
            self.append(f"\r\n[Send error: {exc}]\r\n")
            self.render()
            # Connection is dead: drop it so further keystrokes fall back to
            # local echo instead of retrying the same broken socket forever.
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
            self.connected_label = "Disconnected"
            self.connection_lost_notified = True


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
        with self.recv_condition:
            self.recv_buffer = ""

    def enable_custom_logging(self, file_path: Path) -> None:
        if self.log_enabled:
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = file_path.open("a", encoding="utf-8", errors="replace")
        self.log_enabled = True
        self.append(f"\r\n[Logging started -> {file_path}]\r\n")
        self.render()

    def disable_logging(self) -> None:
        was_enabled = self.log_enabled
        self.log_enabled = False
        try:
            if self.log_file:
                self.log_file.close()
        finally:
            self.log_file = None
        if was_enabled:
            try:
                if self.terminal.winfo_exists():
                    self.append("\r\n[Logging stopped]\r\n")
                    self.render()
            except Exception:
                pass

    def close(self) -> None:
        self.close_sftp_hops()
        try:
            if self.connection:
                self.connection.close()
        finally:
            self.connection = None
            self.connected_label = "Disconnected"
            self.connection_lost_notified = False
            self.disable_logging()

        
    def close_sftp_hops(self) -> None:
        while self.sftp_hops:
            hop = self.sftp_hops.pop()
            try:
                if hop.get("sftp"):
                    hop["sftp"].close()
            except Exception:
                pass
            try:
                if hop.get("client"):
                    hop["client"].close()
            except Exception:
                pass
        self.active_hop_index = 0



@dataclass(eq=False)
class PlaylistItem:
    path: str
    timeout: float
    target_session: TerminalSession
    status: str = "Pending"
