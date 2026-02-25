#!/usr/bin/env bash
# SohnBot Setup Script
# Creates all necessary directories and initializes the project

set -e  # Exit on error

echo "🚀 Setting up SohnBot..."

# Create directory structure
echo "📁 Creating directory structure..."
mkdir -p src/sohnbot/{gateway,runtime,broker,capabilities/{files,git,command_profiles,search,scheduler},persistence,supervision,config}
mkdir -p tests/{unit,integration,fixtures}
mkdir -p config scripts docs data

echo "📝 Creating __init__.py files..."
find src/sohnbot -type d -exec touch {}/__init__.py \;
find tests -type d -exec touch {}/__init__.py \;

# Create .gitkeep for data directory
touch data/.gitkeep

# Copy .env.example to .env if it doesn't exist
if [ ! -f .env ]; then
    echo "🔐 Creating .env from .env.example..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your API keys!"
else
    echo "✓ .env already exists"
fi

# Install dependencies with Poetry (if Poetry is installed)
if command -v poetry &> /dev/null; then
    echo "📦 Installing dependencies with Poetry..."
    poetry install
else
    echo "⚠️  Poetry not found. Install Poetry first:"
    echo "   curl -sSL https://install.python-poetry.org | python3 -"
    echo ""
    echo "   Or install dependencies manually with pip:"
    echo "   pip install -r requirements.txt  # (you'll need to generate this)"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your API keys (ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, BRAVE_API_KEY)"
echo "2. Review config/default.toml for configuration options"
echo "3. Run tests: poetry run pytest"
echo "4. Start development: poetry run python -m sohnbot"
