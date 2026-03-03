#!/usr/bin/env python3
"""Simple local control panel for starting/stopping/restarting SohnBot."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk


class SohnBotControlGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SohnBot Control")
        self.root.geometry("480x190")
        self.root.resizable(False, False)

        self.process: subprocess.Popen[str] | None = None
        self.repo_root = Path(__file__).resolve().parent.parent

        self.status_var = tk.StringVar(value="Status: Stopped")
        self.pid_var = tk.StringVar(value="PID: -")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_lines: list[str] = []
        self.log_window: tk.Toplevel | None = None
        self.log_text: tk.Text | None = None

        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(frame, text="SohnBot Control Panel", font=("Segoe UI", 12, "bold"))
        title.pack(anchor="w")

        status = ttk.Label(frame, textvariable=self.status_var, font=("Segoe UI", 10))
        status.pack(anchor="w", pady=(8, 2))

        pid = ttk.Label(frame, textvariable=self.pid_var, font=("Segoe UI", 10))
        pid.pack(anchor="w", pady=(0, 10))

        buttons = ttk.Frame(frame)
        buttons.pack(anchor="w")

        self.start_button = ttk.Button(buttons, text="Start", width=10, command=self.start_bot)
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.stop_button = ttk.Button(buttons, text="Stop", width=10, command=self.stop_bot)
        self.stop_button.grid(row=0, column=1, padx=(0, 8))

        self.restart_button = ttk.Button(buttons, text="Restart", width=10, command=self.restart_bot)
        self.restart_button.grid(row=0, column=2, padx=(0, 8))

        self.logs_button = ttk.Button(buttons, text="Logs", width=10, command=self.open_logs_window)
        self.logs_button.grid(row=0, column=3)

        note = ttk.Label(
            frame,
            text="Runs: python -m sohnbot (uses current venv / env vars)",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        note.pack(anchor="w", pady=(14, 0))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_ui()
        self.poll_process()
        # Auto-start bot shortly after GUI initialization.
        self.root.after(150, self.start_bot)

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        src_path = str(self.repo_root / "src")
        current = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{current}" if current else src_path
        return env

    def _append_log(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {message}".rstrip()
        self.log_lines.append(line)
        if len(self.log_lines) > 5000:
            self.log_lines = self.log_lines[-5000:]

        if self.log_text is not None:
            self.log_text.insert(tk.END, line + "\n")
            self.log_text.see(tk.END)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)

    def _start_log_reader(self) -> None:
        if self.process is None or self.process.stdout is None:
            return

        def _reader() -> None:
            assert self.process is not None
            assert self.process.stdout is not None
            try:
                for raw in self.process.stdout:
                    self.log_queue.put(raw.rstrip("\n"))
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"[log-reader-error] {exc}")

        threading.Thread(target=_reader, daemon=True).start()

    def start_bot(self) -> None:
        if self.process and self.process.poll() is None:
            return

        venv_scripts = self.repo_root / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        if os.name == "nt":
            preferred = [venv_scripts / "pythonw.exe", venv_scripts / "python.exe"]
        else:
            preferred = [venv_scripts / "python3", venv_scripts / "python"]

        python_bin = None
        for candidate in preferred:
            if candidate.exists():
                python_bin = str(candidate)
                break

        if python_bin is None:
            python_bin = sys.executable

        if os.name == "nt":
            exe_name = os.path.basename(python_bin).lower()
            if exe_name == "python.exe":
                pythonw_candidate = os.path.join(os.path.dirname(python_bin), "pythonw.exe")
                if os.path.exists(pythonw_candidate):
                    python_bin = pythonw_candidate

        cmd = [python_bin, "-m", "sohnbot"]
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "DETACHED_PROCESS"):
                creationflags |= subprocess.DETACHED_PROCESS
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.repo_root),
            env=self._build_env(),
            creationflags=creationflags,
            startupinfo=startupinfo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._append_log(f"Starting SohnBot (PID {self.process.pid})")
        self._start_log_reader()

        self.status_var.set("Status: Running")
        self.pid_var.set(f"PID: {self.process.pid}")
        self.refresh_ui()

    def stop_bot(self) -> None:
        if not self.process or self.process.poll() is not None:
            self.status_var.set("Status: Stopped")
            self.pid_var.set("PID: -")
            self.refresh_ui()
            return

        self.status_var.set("Status: Stopping...")
        self._append_log("Stopping SohnBot...")
        self.refresh_ui()

        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._append_log("Graceful stop timed out; killing process")
            self.process.kill()
            self.process.wait(timeout=5)

        code = self.process.returncode
        self._append_log(f"SohnBot stopped (exit code {code})")
        self.process = None
        self.status_var.set("Status: Stopped")
        self.pid_var.set("PID: -")
        self.refresh_ui()

    def restart_bot(self) -> None:
        self.stop_bot()
        self.start_bot()

    def open_logs_window(self) -> None:
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            self.log_window.focus_force()
            return

        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("SohnBot Logs")
        self.log_window.geometry("900x520")

        container = ttk.Frame(self.log_window, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        text_frame = ttk.Frame(container)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(text_frame, wrap="none", font=("Consolas", 10))
        y_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.log_text.yview)
        x_scroll = ttk.Scrollbar(text_frame, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.log_text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        for line in self.log_lines:
            self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)

        actions = ttk.Frame(container)
        actions.pack(fill=tk.X, pady=(10, 0))

        def clear_logs() -> None:
            self.log_lines.clear()
            if self.log_text is not None:
                self.log_text.delete("1.0", tk.END)

        ttk.Button(actions, text="Clear", command=clear_logs).pack(side=tk.LEFT)
        ttk.Button(actions, text="Close", command=self.log_window.destroy).pack(side=tk.RIGHT)

        def on_logs_close() -> None:
            self.log_window = None
            self.log_text = None

        self.log_window.protocol("WM_DELETE_WINDOW", lambda: (on_logs_close(), self.log_window.destroy()))

    def poll_process(self) -> None:
        self._drain_log_queue()

        if self.process and self.process.poll() is not None:
            code = self.process.returncode
            self._append_log(f"SohnBot exited (code {code})")
            self.status_var.set(f"Status: Exited (code {code})")
            self.pid_var.set("PID: -")
            self.process = None
            self.refresh_ui()

        self.root.after(250, self.poll_process)

    def refresh_ui(self) -> None:
        running = self.process is not None and self.process.poll() is None
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.restart_button.configure(state=tk.NORMAL if running else tk.DISABLED)

    def on_close(self) -> None:
        if self.process and self.process.poll() is None:
            self.stop_bot()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = SohnBotControlGUI(root)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()
