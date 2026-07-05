from __future__ import annotations
import shlex
import threading
import time
from pathlib import Path
from core.connections import SSHConnection, SerialConnection, TelnetConnection
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import TerminalSession

class TeraTermMacroRunner:
    def __init__(self, app: object, session: "TerminalSession"):
        self.app = app
        self.session = session
        self.default_timeout = 60.0
        self.variables: dict[str, str] = {}

    def run_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        for line_no, raw in enumerate(lines, start=1):
            line = self._clean_line(raw)
            if not line: continue

            if "=" in line and not line.lower().startswith("connect"):
                parts = line.split("=", 1)
                var_name, var_value = parts[0].strip(), parts[1].strip()
                if var_name.isidentifier():
                    self.variables[var_name] = self._unquote(var_value)
                    continue

            cmd, arg = self._split_command(line)
            cmd = cmd.lower()

            if arg in self.variables: arg = self.variables[arg]

            if cmd == "end":
                self.session.incoming.put(f"\r\n[TTL line {line_no}: 'end' execution loop terminated successfully]\r\n")
                break

            self.session.incoming.put(f"\r\n[TTL line {line_no}: {cmd}]\r\n")
            if cmd == "connect": self._connect(arg)
            elif cmd == "wait": self._wait(arg)
            elif cmd == "sendln": self.session.send(self._unquote(arg) + "\n")
            elif cmd == "send": self.session.send(self._unquote(arg))
            elif cmd in {"pause", "mpause"}:
                delay = float(self._unquote(arg) or "1")
                if cmd == "mpause": delay /= 1000
                time.sleep(delay)
            else:
                self.session.incoming.put(f"\r\n[TTL warning: unsupported command on line {line_no}: {cmd}]\r\n")


    def _clean_line(self, raw: str) -> str:
        line = raw.strip()
        if not line or line.startswith(";"): return ""
        clean_chars, in_quote, quote_char = [], False, None
        for char in line:
            if char in ("'", '"'):
                if not in_quote: in_quote, quote_char = True, char
                elif char == quote_char: in_quote, quote_char = False, None
            elif char == ";" and not in_quote: break
            clean_chars.append(char)
        return "".join(clean_chars).strip()

    def _split_command(self, line: str) -> tuple[str, str]:
        parts = line.split(None, 1)
        return (parts[0], parts[1].strip()) if len(parts) == 2 else (parts[0], "")

    def _unquote(self, text: str) -> str:
        text = text.strip()
        return text[1:-1] if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'} else text

    def _wait(self, arg: str) -> None:
        pattern = self._unquote(arg)
        if not pattern: return
        if not self.session.wait_for(pattern, self.default_timeout, case_sensitive=True):
            raise TimeoutError(f"wait timed out for: {pattern}")

    def _connect(self, arg: str) -> None:
        parts = shlex.split(self._unquote(arg))
        if not parts: raise ValueError("connect requires host")
        host, username, password, port, is_telnet = parts[0], "", "", None, False

        for item in parts[1:]:
            lower = item.lower()
            if lower in ("/telnet", "/t"): is_telnet = True
            elif lower.startswith("/user="): username = item.split("=", 1)[1]
            elif lower.startswith("/passwd=") or lower.startswith("/password="): password = item.split("=", 1)[1]
            elif lower.startswith("/port="): port = int(item.split("=", 1)[1])

        if port is None: port = 23 if is_telnet else 22
        done = threading.Event()
        result: dict[str, Exception | None] = {"error": None}

        def connect_on_ui_thread():
            try:
                if is_telnet: conn, lbl = TelnetConnection(host=host, port=port), f"Telnet {host}"
                else: conn, lbl = SSHConnection(host=host, username=username, password=password, port=port, look_for_keys=False, allow_agent=False), f"SSH {host}"
                self.app.connect_session(self.session, conn, lbl)
            except Exception as exc: result["error"] = exc
            finally: done.set()

        self.app.after(0, connect_on_ui_thread)
        done.wait(timeout=30)
        if result["error"]: raise result["error"]
        if not done.is_set(): raise TimeoutError("TTL connect timed out")
        time.sleep(0.5)


def execute_python_script_sync(session: "TerminalSession", path: str):
    def send(text: str, newline: bool = True, delay: float = 0.0):
        if delay: time.sleep(delay)
        session.send(str(text) + ("\n" if newline else ""))

    def print_to_terminal(*args, sep=" ", end="\n"):
        text = sep.join(str(a) for a in args) + end
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        session.incoming.put(text)


    def connect_ssh(host, username, password, port=22):
        conn = SSHConnection(host=host, username=username, password=password, port=port, look_for_keys=False, allow_agent=False)
        session.app.connect_session(session, conn, f"SSH {host}"); time.sleep(1.0)

    def connect_serial(port, baudrate, bytesize=8, parity="N", stopbits=1.0):
        conn = SerialConnection(port=port, baudrate=baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits)
        session.app.connect_session(session, conn, f"Serial {port} @ {baudrate}"); time.sleep(1.0)

    def connect_telnet(host, port=23):
        conn = TelnetConnection(host=host, port=port)
        session.app.connect_session(session, conn, f"Telnet {host}"); time.sleep(1.0)

    code = Path(path).read_text(encoding="utf-8")
    globs = {
        "__file__": path, "__name__": "__automation__", 
        "send": send, "print": print_to_terminal, 
        "connect_ssh": connect_ssh, "connect_serial": connect_serial, "connect_telnet": connect_telnet,
        "wait": time.sleep, "sleep": time.sleep, "terminal_name": session.name
    }
    exec(compile(code, path, "exec"), globs, {})