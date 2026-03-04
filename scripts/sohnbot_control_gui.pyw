#!/usr/bin/env python3
"""Simple local control panel for starting/stopping/restarting SohnBot."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import json
from pathlib import Path
from tkinter import messagebox, ttk


class SohnBotControlGUI:
    _COLLAPSED_GEOMETRY = "600x220"
    _EXPANDED_GEOMETRY = "960x620"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SohnBot Control")
        self.root.geometry(self._COLLAPSED_GEOMETRY)
        self.root.resizable(True, True)

        self.process: subprocess.Popen[str] | None = None
        self.repo_root = Path(__file__).resolve().parent.parent
        self.launch_log_path = self.repo_root / "data" / "gui-launcher.log"
        self.instance_lock_path = self.repo_root / "data" / "sohnbot.instance.lock"

        self.status_var = tk.StringVar(value="Status: Stopped")
        self.pid_var = tk.StringVar(value="PID: -")
        self.logs_button_var = tk.StringVar(value="Show Logs")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_lines: list[str] = []
        self.log_text: tk.Text | None = None
        self.logs_visible = False

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

        self.logs_button = ttk.Button(buttons, textvariable=self.logs_button_var, width=10, command=self.toggle_logs)
        self.logs_button.grid(row=0, column=3)

        note = ttk.Label(
            frame,
            text="Runs: python -m sohnbot (uses current venv / env vars)",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        note.pack(anchor="w", pady=(14, 0))

        self.logs_container = ttk.Frame(frame)

        text_frame = ttk.Frame(self.logs_container)
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

        actions = ttk.Frame(self.logs_container)
        actions.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(actions, text="Clear", command=self.clear_logs).pack(side=tk.LEFT)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_ui()
        self.poll_process()
        # Auto-start bot shortly after GUI initialization.
        self.root.after(150, lambda: self.start_bot(interactive=False))

    def _observability_port(self) -> int:
        """Read observability HTTP port from env/.env with safe fallback."""
        env_value = os.getenv("SOHNBOT_OBSERVABILITY_HTTP_PORT")
        if env_value:
            try:
                return int(env_value)
            except ValueError:
                pass

        env_file = self.repo_root / ".env"
        try:
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() != "SOHNBOT_OBSERVABILITY_HTTP_PORT":
                    continue
                return int(value.strip().strip("'\""))
        except Exception:
            pass
        return 8085

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        src_path = str(self.repo_root / "src")
        current = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{current}" if current else src_path
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def _resolve_command(self) -> list[str]:
        """Resolve launch command, preferring direct venv Python to avoid wrapper PID drift."""
        venv_scripts = self.repo_root / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        if os.name == "nt":
            preferred = [venv_scripts / "python.exe", venv_scripts / "pythonw.exe"]
        else:
            preferred = [venv_scripts / "python3", venv_scripts / "python"]

        for candidate in preferred:
            if candidate.exists():
                return [str(candidate), "-m", "sohnbot"]

        poetry = shutil.which("poetry")
        if poetry:
            return [poetry, "run", "python", "-m", "sohnbot"]

        return [sys.executable, "-m", "sohnbot"]

    def _write_launcher_log(self, message: str) -> None:
        try:
            self.launch_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.launch_log_path.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except Exception:
            pass

    def _is_pid_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _active_lock_pid(self) -> int | None:
        """Return active lock-holder PID written by runtime guard, if any."""
        try:
            payload = self.instance_lock_path.read_text(encoding="utf-8").strip()
            pid = int(payload)
        except Exception:
            return None
        return pid if self._is_pid_running(pid) else None

    def _port_owner_pid(self, port: int) -> int | None:
        """Return owning PID for listening localhost port on Windows."""
        if os.name != "nt":
            return None
        script = (
            f"$conn = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty OwningProcess; "
            "if ($conn) { $conn }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                check=False,
            )
        except Exception:
            return None
        text = (result.stdout or "").strip()
        if not text:
            return None
        try:
            pid = int(text)
        except ValueError:
            return None
        return pid if self._is_pid_running(pid) else None

    def _find_existing_sohnbot_processes(self) -> list[dict[str, str]]:
        """Best-effort discovery of already running SohnBot processes."""
        if os.name != "nt":
            return []
        script = (
            "$procs = Get-CimInstance Win32_Process | Where-Object { "
            "$_.Name -match '^pythonw?(\\.exe)?$' -and "
            "$_.CommandLine -and "
            "$_.CommandLine -match 'python(w)?(\\.exe)?\\s+-m\\s+sohnbot' }; "
            "$procs | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"Process discovery failed: {exc}")
            return []

        payload = (result.stdout or "").strip()
        if not payload:
            return []
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            self._append_log("Process discovery returned non-JSON output")
            return []
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return []

        current_pid = os.getpid()
        managed_pid = self.process.pid if self.process and self.process.poll() is None else None
        discovered: list[dict[str, str]] = []
        for row in parsed:
            if not isinstance(row, dict):
                continue
            pid_raw = row.get("ProcessId")
            try:
                pid = int(pid_raw)
            except Exception:  # noqa: BLE001
                continue
            if pid in {current_pid, managed_pid}:
                continue
            discovered.append(
                {
                    "pid": str(pid),
                    "name": str(row.get("Name") or ""),
                    "command": str(row.get("CommandLine") or ""),
                }
            )
        return discovered

    def _kill_processes(self, pids: list[int]) -> tuple[bool, str]:
        """Kill PIDs on Windows using taskkill /T /F."""
        if not pids:
            return True, ""
        if os.name != "nt":
            return False, "Automatic kill prompt is only implemented for Windows."
        errors: list[str] = []
        for pid in pids:
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=8,
                )
            except subprocess.TimeoutExpired:
                errors.append(f"PID {pid}: taskkill timed out after 8s")
                continue
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                stdout = (result.stdout or "").strip()
                errors.append(f"PID {pid}: {stderr or stdout or 'taskkill failed'}")
        if errors:
            return False, "\n".join(errors)
        return True, ""

    def _append_log(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {message}".rstrip()
        self.log_lines.append(line)
        if len(self.log_lines) > 5000:
            self.log_lines = self.log_lines[-5000:]

        if self.log_text is not None:
            self.log_text.insert(tk.END, line + "\n")
            self.log_text.see(tk.END)

    def clear_logs(self) -> None:
        self.log_lines.clear()
        if self.log_text is not None:
            self.log_text.delete("1.0", tk.END)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)

    def _start_log_reader(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return

        def _reader(proc: subprocess.Popen[str]) -> None:
            assert proc.stdout is not None
            try:
                for raw in proc.stdout:
                    line = raw.rstrip("\n")
                    self.log_queue.put(line)
                    self._write_launcher_log(line)
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"[log-reader-error] {exc}")
                self._write_launcher_log(f"[log-reader-error] {exc}")

        threading.Thread(target=_reader, args=(process,), daemon=True).start()

    def start_bot(self, interactive: bool = True) -> None:
        if self.process and self.process.poll() is None:
            return

        observability_port = self._observability_port()
        port_owner_pid = self._port_owner_pid(observability_port)
        if port_owner_pid is not None:
            if not interactive:
                self._append_log(
                    f"Auto-start skipped: port {observability_port} already in use by PID {port_owner_pid}."
                )
                self.status_var.set("Status: Running (port in use)")
                self.pid_var.set("PID: External")
                self.refresh_ui()
                return

            answer = messagebox.askyesno(
                "Port Already In Use",
                f"Port {observability_port} is already in use by PID {port_owner_pid}. "
                "Do you want to terminate it and restart SohnBot?",
            )
            if not answer:
                self._append_log(
                    f"Start cancelled: port {observability_port} is in use by PID {port_owner_pid}."
                )
                return
            ok, err = self._kill_processes([port_owner_pid])
            if not ok:
                messagebox.showerror(
                    "Failed to Kill Existing Instance",
                    "Could not terminate process owning observability port:\n\n" + err,
                )
                self._append_log(f"Failed to terminate port owner PID {port_owner_pid}: {err}")
                return
            self._append_log(f"Terminated port owner PID {port_owner_pid} (port {observability_port}).")

        lock_pid = self._active_lock_pid()
        if lock_pid is not None:
            if not interactive:
                self._append_log(f"Auto-start skipped: active SohnBot lock detected (PID {lock_pid}).")
                self.status_var.set("Status: Running (lock detected)")
                self.pid_var.set("PID: External")
                self.refresh_ui()
                return

            answer = messagebox.askyesno(
                "Existing SohnBot Instance",
                "An active SohnBot lock was detected "
                f"(PID {lock_pid}). Do you want to terminate it and restart?",
            )
            if not answer:
                self._append_log("Start cancelled: active SohnBot lock detected.")
                return

            ok, err = self._kill_processes([lock_pid])
            if not ok:
                messagebox.showerror(
                    "Failed to Kill Existing Instance",
                    "Could not terminate lock-holder process:\n\n" + err,
                )
                self._append_log(f"Failed to terminate lock-holder PID {lock_pid}: {err}")
                return
            self._append_log(f"Terminated lock-holder PID {lock_pid}.")

        existing = self._find_existing_sohnbot_processes()
        if existing:
            if not interactive:
                existing_pids = ", ".join(item["pid"] for item in existing[:5])
                suffix = f" (+{len(existing) - 5} more)" if len(existing) > 5 else ""
                self._append_log(
                    "Auto-start skipped: detected existing SohnBot instance(s): "
                    f"{existing_pids}{suffix}"
                )
                self.status_var.set("Status: Running (external instance detected)")
                self.pid_var.set("PID: External")
                self.refresh_ui()
                return
            preview = "\n".join(
                f"- PID {item['pid']} | {item['name']} | {item['command'][:120]}"
                for item in existing[:5]
            )
            if len(existing) > 5:
                preview += f"\n... and {len(existing) - 5} more"
            answer = messagebox.askyesno(
                "Existing SohnBot Instance",
                "Another SohnBot instance appears to be running:\n\n"
                f"{preview}\n\n"
                "Do you want to kill it and start a fresh instance?",
            )
            if not answer:
                self._append_log("Start cancelled: existing SohnBot instance detected.")
                return
            pids = [int(item["pid"]) for item in existing]
            ok, err = self._kill_processes(pids)
            if not ok:
                messagebox.showerror(
                    "Failed to Kill Existing Instance",
                    "Could not terminate existing SohnBot process(es):\n\n" + err,
                )
                self._append_log(f"Failed to terminate existing processes: {err}")
                return
            self._append_log(f"Terminated existing SohnBot process(es): {', '.join(item['pid'] for item in existing)}")

        cmd = self._resolve_command()
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        env = self._build_env()
        self._append_log(f"Launching: {' '.join(cmd)}")
        self._append_log(f"CWD: {self.repo_root}")
        self._append_log(f"Launcher log: {self.launch_log_path}")
        self._write_launcher_log(f"==== START {time.strftime('%Y-%m-%d %H:%M:%S')} ====")
        self._write_launcher_log(f"cmd={' '.join(cmd)}")
        self._write_launcher_log(f"cwd={self.repo_root}")
        self._write_launcher_log(f"pythonpath={env.get('PYTHONPATH','')}")

        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.repo_root),
            env=env,
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
        self._start_log_reader(self.process)

        self.status_var.set("Status: Running")
        self.pid_var.set(f"PID: {self.process.pid}")
        self.refresh_ui()

    def stop_bot(self) -> None:
        self.status_var.set("Status: Stopping...")
        self._append_log("Stopping SohnBot...")
        self.refresh_ui()

        target_pids: list[int] = []
        if self.process and self.process.poll() is None:
            target_pids.append(self.process.pid)

        # Also stop any externally launched SohnBot instances.
        for item in self._find_existing_sohnbot_processes():
            try:
                target_pids.append(int(item["pid"]))
            except Exception:  # noqa: BLE001
                continue

        deduped = sorted({pid for pid in target_pids if pid > 0})
        if deduped:
            ok, err = self._kill_processes(deduped)
            if ok:
                self._append_log(f"SohnBot process(es) terminated: {', '.join(str(pid) for pid in deduped)}")
                self._write_launcher_log(f"stopped pids={','.join(str(pid) for pid in deduped)}")
            else:
                self._append_log(f"Failed to terminate some process(es): {err}")
                self._write_launcher_log(f"stop_failed error={err}")
        else:
            self._append_log("No running SohnBot process found.")
            self._write_launcher_log("stopped no_process_found")

        self.process = None
        self.status_var.set("Status: Stopped")
        self.pid_var.set("PID: -")
        self.refresh_ui()

    def restart_bot(self) -> None:
        self.stop_bot()
        self.start_bot()

    def toggle_logs(self) -> None:
        if self.logs_visible:
            self.logs_container.pack_forget()
            self.logs_visible = False
            self.logs_button_var.set("Show Logs")
            self.root.geometry(self._COLLAPSED_GEOMETRY)
            return

        self.logs_container.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.logs_visible = True
        self.logs_button_var.set("Hide Logs")
        self.root.geometry(self._EXPANDED_GEOMETRY)
        if self.log_text is not None:
            self.log_text.delete("1.0", tk.END)
            for line in self.log_lines:
                self.log_text.insert(tk.END, line + "\n")
            self.log_text.see(tk.END)

    def poll_process(self) -> None:
        self._drain_log_queue()

        if self.process and self.process.poll() is not None:
            code = self.process.returncode
            self._append_log(f"SohnBot exited (code {code})")
            self._write_launcher_log(f"exited exit_code={code}")
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
