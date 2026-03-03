# SohnBot

Policy-enforced local autonomous execution system with Telegram interface.

## Overview

SohnBot is an autonomous agent that executes file operations, git commands, scheduled tasks, and web searches through a centralized broker layer that enforces safety boundaries and operation policies.

## Features

- **Broker-Centric Architecture**: All operations route through policy enforcement layer
- **Telegram Interface**: Natural language interaction via Telegram Bot API
- **Claude Agent SDK**: Powered by Anthropic's Claude models
- **Safety-First Design**: Scope validation, path traversal prevention, operation classification
- **Scheduled Automation**: Idempotent job execution with timezone awareness
- **Two-Tier Configuration**: Static and dynamic config with hot-reload support

## Requirements

- Python 3.13+
- Poetry
- Git 2.x+ — **runtime dependency** required for snapshot branch creation (must be in PATH)
- ripgrep (`rg`) — required for file search operations (must be in PATH)
- Telegram Bot Token (from @BotFather)
- **Claude Authentication** (choose one):
  - **Option A**: OAuth Token (recommended for Claude Pro/Max users) - get via `claude setup-token`
  - **Option B**: Anthropic API Key (pay-per-use) - get from https://console.anthropic.com/
- Brave Search API Key (optional, for web search)

## Installation

```bash
# Install system dependencies

# git (required at runtime for snapshot operations)
# On macOS — usually pre-installed; if not:
brew install git

# On Ubuntu/Debian
sudo apt-get install git

# On Windows (via Chocolatey)
choco install git

# ripgrep (required at runtime for file search)
# On macOS
brew install ripgrep

# On Ubuntu/Debian
sudo apt-get install ripgrep

# On Windows (via Chocolatey)
choco install ripgrep

# Install Python dependencies with Poetry
poetry install

# Copy environment template
cp .env.example .env

# Edit .env with your API keys
# ANTHROPIC_API_KEY=your_key_here
# TELEGRAM_BOT_TOKEN=your_token_here
# BRAVE_API_KEY=your_key_here
```

## Runtime CLI Dependencies

SohnBot shells out to the following CLI tools at runtime. Both must be available in PATH when the bot process starts:

| Tool | Used for | Fails if missing |
|------|----------|------------------|
| `git` | Snapshot branch creation before file edits (FR-005) | Patch operations raise `git_not_found` |
| `rg` (ripgrep) | File content search (FR-009) | Search operations raise `search_failed` |

> **Windows note:** Git for Windows installs `git.exe` to PATH automatically. ripgrep must be installed separately.

## Configuration

Configuration is managed through:
- `config/default.toml` - Default configuration values
- `.env` - Secret API keys and tokens
- SQLite database - Dynamic configuration (hot-reloadable)

See `config/default.toml` for all available configuration options.

## Running SohnBot

### 1. Set Required Configuration

Ensure your `.env` file is configured with required values:

```bash
# Edit .env with your authentication credentials

# Choose ONE of these authentication methods:

# Option A: OAuth Token (Recommended for Claude Pro/Max users)
# Run: claude setup-token
# Then copy the token here:
# CLAUDE_CODE_OAUTH_TOKEN=your_oauth_token_here

# Option B: Anthropic API Key (Pay-per-use)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Required: Telegram Bot Token
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Optional: Web search
BRAVE_API_KEY=your_brave_api_key_here
```

**Authentication Methods Explained:**
- **OAuth Token**: If you have Claude Pro or Max subscription, use this. Run `claude setup-token` to generate it. Uses your subscription quota.
- **API Key**: Pay-per-use pricing. Get from [Anthropic Console](https://console.anthropic.com/).

**Note**: You only need ONE authentication method, not both. The SDK checks for OAuth token first, then falls back to API key.

You also need to configure **allowed chat IDs** to authorize Telegram users. Add this to your `.env`:

```bash
# Comma-separated list of allowed Telegram chat IDs
SOHNBOT_TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
```

**How to find your Telegram chat ID:**
1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It will reply with your chat ID (a number)
3. Add that number to `SOHNBOT_TELEGRAM_ALLOWED_CHAT_IDS`

### 2. Run Database Migrations

Initialize the database schema:

```bash
poetry run python scripts/migrate.py
```

This creates the SQLite database with all required tables.

### 3. Start SohnBot

Run the bot:

```bash
poetry run python -m sohnbot
```

You should see log output showing:
- ✅ Telegram gateway started
- ✅ Scheduler executor started
- ✅ Snapshot collector started
- ✅ HTTP observability server started (if enabled)

### 4. Find Your Bot on Telegram

1. Open Telegram
2. Search for your bot by username (the one you created with @BotFather)
3. Send `/start` to begin interacting
4. Send `/help` to see all available commands

**Note:** Only chat IDs in `SOHNBOT_TELEGRAM_ALLOWED_CHAT_IDS` will be able to interact with the bot. Unauthorized messages are silently ignored.

## User Guide

**📖 For end users:** See **[USER_GUIDE.md](docs/USER_GUIDE.md)** for:
- Complete command reference
- Natural language examples
- Safety features and best practices
- Troubleshooting guide

**Quick start:** Send `/help` to the bot for a command overview.

## Project Structure

```
sohnbot/
├── src/sohnbot/          # Main source code
│   ├── gateway/          # Telegram interface
│   ├── runtime/          # Claude Agent SDK integration
│   ├── broker/           # Policy enforcement (architectural heart)
│   ├── capabilities/     # File, Git, Scheduler, Search modules
│   ├── persistence/      # SQLite management
│   ├── supervision/      # Health monitoring
│   └── config/           # Configuration management
├── tests/                # Test suite
├── config/               # Configuration files
└── scripts/              # Utility scripts
```

## Development

```bash
# Run tests
poetry run pytest

# Run linter
poetry run ruff check .

# Format code
poetry run black .

# Type checking
poetry run mypy src/
```

## License

Private project - All rights reserved.
