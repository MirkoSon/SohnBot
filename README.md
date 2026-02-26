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
- Git
- ripgrep (rg) - Required for file search operations
- Telegram Bot Token (from @BotFather)
- Anthropic API Key
- Brave Search API Key (optional, for web search)

## Installation

```bash
# Install system dependencies
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

## Configuration

Configuration is managed through:
- `config/default.toml` - Default configuration values
- `.env` - Secret API keys and tokens
- SQLite database - Dynamic configuration (hot-reloadable)

See `config/default.toml` for all available configuration options.

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
