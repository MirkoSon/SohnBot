# SohnBot Development Environment Guide

This document outlines the requirements and setup instructions for developing SohnBot across various environments, specifically addressing the differences between Windows CMD, WSL, and cloud instances.

## Core Dependencies

To run SohnBot successfully, you must have the following system binaries installed and accessible in your system's PATH:

*   **Node.js**: Required for running the AI agent framework scripts (e.g., `_bmad/bmm/scripts/bmm.js`).
    *   Minimum version: v18+ (LTS recommended)
*   **Python**: Required for the main application (`src/main.py`).
    *   Minimum version: 3.10+
*   **Git**: Required for snapshot branch creation and rollback operations (FR-005, FR-006).
    *   Minimum version: 2.x+
*   **ripgrep (`rg`)**: Required for file content search operations (FR-003).
    *   Minimum version: 11.0+
*   **Poetry**: Required for Python dependency management.

## Environment-Specific Setup

### Windows (CMD / PowerShell)

1.  **Node.js**: Install via the official Windows installer from nodejs.org. Ensure the option to add to PATH is selected.
2.  **Python & Poetry**: Install Python from python.org. Install Poetry using the official PowerShell script: `(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -`.
3.  **Git**: Install Git for Windows from git-scm.com. The installer automatically adds git to PATH.
4.  **ripgrep**: Install via Chocolatey (`choco install ripgrep`) or download from the GitHub releases page (https://github.com/BurntSushi/ripgrep/releases). Ensure `rg.exe` is in PATH.
5.  **Command Execution**: When tools need to run commands, Windows executes them via `cmd /c`. Ensure any scripts that wrap commands handle path separators (`\` vs `/`) correctly.

### Windows Subsystem for Linux (WSL)

When developing in WSL (e.g., Ubuntu), remember that the Linux file system and binaries are separate from your Windows host.

1.  **Node.js**: We recommend using `nvm` (Node Version Manager) to install Node.js inside WSL. Do not rely on the Windows Node.js installation executable through WSL interoperability.
2.  **Python & Poetry**: Install via `apt` (e.g., `sudo apt install python3 python3-pip`). Install Poetry using the curl script: `curl -sSL https://install.python-poetry.org | python3 -`.
3.  **Git**: Usually pre-installed in WSL. If not, install via `sudo apt install git`.
4.  **ripgrep**: Install via `apt`: `sudo apt install ripgrep`.
5.  **Command Execution**: Scripts running in WSL will use `bash` (or `sh`).
6.  **Important**: Ensure that if you access files located on the Windows host (`/mnt/c/...`), the performance may be slower, and file permissions might behave differently than in a native Linux filesystem. It's generally recommended to clone the repository natively within the WSL file system (`~/<your-projects>`).

### Cloud / Remote Servers (Linux)

1.  Similar to WSL, ensure all dependencies (Node.js, Python, Git, ripgrep) are installed natively via the package manager for your specific distribution:
    *   **Debian/Ubuntu**: `sudo apt install nodejs python3 python3-pip git ripgrep`
    *   **RHEL/CentOS/Fedora**: `sudo yum install nodejs python3 python3-pip git ripgrep`
    *   **Alpine**: `apk add nodejs python3 py3-pip git ripgrep`
2.  Install Poetry using the curl script: `curl -sSL https://install.python-poetry.org | python3 -`
3.  Scripts expect a standard Bash (`/bin/bash` or `/bin/sh`) environment.

## Troubleshooting Binary Identification

A common issue across mixed environments is a script failing because it cannot locate required binaries (`node`, `python`, `git`, `rg`).
*   **Verify PATH**: Run the following commands in your terminal to verify each binary is accessible:
    *   `node -v` (should show Node.js version)
    *   `python --version` or `python3 --version` (should show Python version)
    *   `git --version` (should show Git version)
    *   `rg --version` (should show ripgrep version)
*   If any command returns an error, the binary is missing or not in your PATH.
*   **Windows + WSL**: If a script running *inside WSL* tries to run a command that is only installed on Windows, it will likely fail. You must install the required dependencies inside WSL.

## Testing Your Setup

After setting up your environment, run the following verification commands from the project root:

```bash
# Verify Python
poetry env info
poetry run python --version

# Verify Node
node -v

# Verify Git
git --version

# Verify ripgrep
rg --version

# Run the health check script (if available)
# node scripts/checkDatabaseHealth.js
```

All commands should execute without "command not found" errors. If any fail, revisit the installation steps for your specific environment above.
