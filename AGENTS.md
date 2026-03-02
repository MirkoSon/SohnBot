# AGENTS Instructions

## Test Execution Policy
- Do not run long `pytest` jobs attached to the interactive session.
- For full-suite runs or runs likely to take more than 30 seconds, run detached with PID + status tracking:
  `nohup bash -lc 'source .venv/bin/activate; echo "START $(date -Is)" > /tmp/pytest.status; timeout --signal=TERM 1800 pytest -q > /tmp/pytest.log 2>&1; ec=$?; echo "EXIT $ec $(date -Is)" >> /tmp/pytest.status' </dev/null >/tmp/pytest-launch.log 2>&1 & echo $! >/tmp/pytest.pid`
- Report progress and results by reading the log file (for example, `tail -n 200 /tmp/pytest.log`).
- Check status with `cat /tmp/pytest.status` and process state with `ps -p $(cat /tmp/pytest.pid) -o pid,ppid,stat,etime,cmd`.
- Treat `EXIT ...` in `/tmp/pytest.status` as authoritative completion, even if a stale pytest process still appears in `ps`.
- Prefer targeted test files first, then broader batches, then full suite.
- Avoid background PTY jobs that depend on the current Codex session lifecycle.
