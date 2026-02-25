# SohnBot Setup Script (PowerShell for Windows)
# Creates all necessary directories and initializes the project

Write-Host "🚀 Setting up SohnBot..." -ForegroundColor Green

# Create directory structure
Write-Host "📁 Creating directory structure..." -ForegroundColor Cyan
$directories = @(
    "src\sohnbot\gateway",
    "src\sohnbot\runtime",
    "src\sohnbot\broker",
    "src\sohnbot\capabilities\files",
    "src\sohnbot\capabilities\git",
    "src\sohnbot\capabilities\command_profiles",
    "src\sohnbot\capabilities\search",
    "src\sohnbot\capabilities\scheduler",
    "src\sohnbot\persistence",
    "src\sohnbot\supervision",
    "src\sohnbot\config",
    "tests\unit",
    "tests\integration",
    "tests\fixtures",
    "config",
    "scripts",
    "docs",
    "data"
)

foreach ($dir in $directories) {
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

# Create __init__.py files
Write-Host "📝 Creating __init__.py files..." -ForegroundColor Cyan
Get-ChildItem -Path "src\sohnbot" -Recurse -Directory | ForEach-Object {
    $initFile = Join-Path $_.FullName "__init__.py"
    if (!(Test-Path $initFile)) {
        New-Item -ItemType File -Path $initFile -Force | Out-Null
    }
}

Get-ChildItem -Path "tests" -Recurse -Directory | ForEach-Object {
    $initFile = Join-Path $_.FullName "__init__.py"
    if (!(Test-Path $initFile)) {
        New-Item -ItemType File -Path $initFile -Force | Out-Null
    }
}

# Create .gitkeep for data directory
if (!(Test-Path "data\.gitkeep")) {
    New-Item -ItemType File -Path "data\.gitkeep" -Force | Out-Null
}

# Copy .env.example to .env if it doesn't exist
if (!(Test-Path ".env")) {
    Write-Host "🔐 Creating .env from .env.example..." -ForegroundColor Cyan
    Copy-Item ".env.example" ".env"
    Write-Host "⚠️  Please edit .env and add your API keys!" -ForegroundColor Yellow
} else {
    Write-Host "✓ .env already exists" -ForegroundColor Green
}

# Install dependencies with Poetry (if Poetry is installed)
if (Get-Command poetry -ErrorAction SilentlyContinue) {
    Write-Host "📦 Installing dependencies with Poetry..." -ForegroundColor Cyan
    poetry install
} else {
    Write-Host "⚠️  Poetry not found. Install Poetry first:" -ForegroundColor Yellow
    Write-Host "   (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -"
    Write-Host ""
    Write-Host "   Or install dependencies manually with pip:"
    Write-Host "   pip install claude-agent-sdk python-telegram-bot aiosqlite structlog python-dotenv"
}

Write-Host ""
Write-Host "✅ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Edit .env and add your API keys (ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, BRAVE_API_KEY)"
Write-Host "2. Review config\default.toml for configuration options"
Write-Host "3. Run tests: poetry run pytest"
Write-Host "4. Start development: poetry run python -m sohnbot"
