# Installation Steps for Failover System

After implementing the Claude-to-Gemini failover system, you need to:

## 1. Update Poetry Lock File

```bash
poetry lock
```

This updates `poetry.lock` to include the new `google-generativeai` dependency.

## 2. Install Dependencies

```bash
poetry install
```

## 3. Enable Gemini Delegation (Opt-In)

⚠️ **Security Note**: Gemini delegation sends prompts to Google's API. Only enable if you understand the data privacy implications.

```bash
# Option A: Enable via Telegram (when SohnBot is running)
/config set runtime.gemini_delegation_enabled true

# Option B: Update database directly (before starting)
sqlite3 data/sohnbot.db "INSERT OR REPLACE INTO config (key, value) VALUES ('runtime.gemini_delegation_enabled', 'true');"
```

## 4. Restart SohnBot

```bash
poetry run python -m sohnbot
```

## 5. Verify Setup

```bash
# Check agent status
/agent

# Check configuration
/config get runtime.gemini_delegation_enabled
```

## Configuration Options

### Required
- `GOOGLE_API_KEY` or `GEMINI_API_KEY` in `.env`

### Optional
- `runtime.gemini_delegation_enabled` (default: `false`)
  - Set to `true` to allow Claude to delegate tasks to Gemini
  - ⚠️ Data privacy: Prompts sent to Google

### Security Considerations

**Before enabling Gemini delegation, understand:**

1. **Data Leaves Trust Boundary**
   - Prompts delegated to Gemini are sent to Google's API
   - Google may log/process this data per their terms

2. **What Gets Delegated**
   - Only prompts Claude explicitly sends to the delegation tool
   - File contents are NOT automatically included (unless Claude adds them to prompt)

3. **Automatic Failover**
   - When Claude hits rate limits, Gemini takes over automatically
   - This ONLY handles conversations (no file access)
   - Doesn't send previous file contents

4. **Recommended Use**
   - Safe: Code analysis, explanations, general Q&A
   - Risky: Analysis of proprietary code, business logic
   - Never: Secrets, API keys, sensitive data

## Testing

### Test Delegation (if enabled)

```
You: Ask Claude to explain async/await in Python
Claude: [May use ai__delegate_to_gemini if beneficial]
```

### Test Failover

1. Temporarily set invalid Claude credentials
2. Send a message
3. Verify Gemini takes over
4. Check status: `/agent`
5. Restore credentials
6. Verify auto-recovery

## Troubleshooting

### "Gemini delegation is disabled"

```bash
/config set runtime.gemini_delegation_enabled true
```

### API Key Not Found

```bash
# Check .env has one of:
GOOGLE_API_KEY=your_key
# OR
GEMINI_API_KEY=your_key

# Restart SohnBot
```

### Poetry Lock Conflict

```bash
# Remove old lock and regenerate
rm poetry.lock
poetry lock
poetry install
```
