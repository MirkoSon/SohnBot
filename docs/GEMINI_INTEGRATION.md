# Gemini Integration Guide

This guide explains how to use Google's Gemini Pro to save Claude quota by delegating complex reasoning tasks.

## Overview

SohnBot supports **AI delegation** where Claude (running on cost-effective Haiku) can delegate complex reasoning tasks to Google's Gemini Pro. This allows you to:

- **Save Claude quota** for Claude Pro/Max subscribers
- **Reduce API costs** for pay-per-use users
- **Distribute workload** across multiple AI providers
- **Maintain quality** while optimizing costs

## How It Works

```
User Request → Claude (Haiku/Sonnet) → Decision:
                                        ├─ Simple task → Claude handles it
                                        └─ Complex reasoning → Delegate to Gemini
                                                             ↓
                                                        Gemini processes
                                                             ↓
                                                        Claude formats response
                                                             ↓
                                                        User receives answer
```

Claude acts as an **intelligent orchestrator** that:
1. Receives your request
2. Determines if delegation would be beneficial
3. Delegates to Gemini when appropriate
4. Formats and presents the results

## Setup

### 1. Get Google API Key

Visit [Google AI Studio](https://aistudio.google.com/app/apikey) and create an API key.

### 2. Add to Environment

Edit your `.env` file:
```bash
GOOGLE_API_KEY=your_google_api_key_here
```

### 3. Install Dependency

```bash
poetry add google-generativeai
```

Or if already installed:
```bash
poetry install
```

### 4. Restart SohnBot

```bash
poetry run python -m sohnbot
```

## When Claude Uses Gemini

Claude automatically considers Gemini delegation for:

### ✅ Good Candidates for Delegation

- **Code Analysis**: "Review this code for bugs and performance issues"
- **Document Summarization**: "Summarize this 50-page document"
- **Research Synthesis**: "Compare React vs Vue based on latest trends"
- **Complex Explanations**: "Explain how transformers work in ML"
- **Data Analysis**: "Analyze this dataset and find patterns"
- **Architectural Review**: "Review this system design for scalability"

### ❌ NOT Suitable for Delegation

Tasks requiring SohnBot capabilities:
- File operations (read/write/edit)
- Git commands (status/commit/rollback)
- Scheduled job management
- Web search (use `web__search` tool instead)
- System health checks

## Usage Examples

### Example 1: Code Review

**You:**
```
Review this Python function for potential issues:

def process_data(items):
    result = []
    for item in items:
        if item > 0:
            result.append(item * 2)
    return result
```

**Claude:**
- Recognizes this is pure code analysis
- Uses `ai__delegate_to_gemini` tool
- Gemini analyzes the code
- Claude formats and presents findings

**Response:**
```
🤖 Gemini Response:

Code Review Findings:
1. Performance: Uses list.append in loop (O(n²) worst case)
   Suggestion: Use list comprehension
2. Type Hints: Missing type annotations
3. Validation: No input validation for items parameter
4. Edge Cases: Doesn't handle empty list explicitly

Improved version:
def process_data(items: list[int]) -> list[int]:
    return [item * 2 for item in items if item > 0]
```

### Example 2: Architecture Discussion

**You:**
```
Should I use microservices or monolith for a startup with 5 developers?
```

**Claude:**
- Recognizes this is a reasoning/research task
- Delegates to Gemini for analysis
- Presents comprehensive comparison

### Example 3: Task That Stays with Claude

**You:**
```
Read config/default.toml and show me the scheduler settings
```

**Claude:**
- Recognizes file operation required
- Uses `fs__read` tool (via Broker)
- Processes request without delegation
- Returns file contents

## Cost Analysis

### Pricing Comparison (per 1M tokens)

| Provider | Model | Input | Output | Use Case |
|----------|-------|-------|--------|----------|
| Anthropic | Haiku 4.5 | $0.25 | $1.25 | Simple orchestration |
| Anthropic | Sonnet 4.6 | $3.00 | $15.00 | Complex file ops |
| **Google** | **Gemini 2.0 Flash** | **$0.075** | **$0.30** | **Complex reasoning** |

### Example Cost Calculation

**Scenario**: Code review of 5,000 token file

**Without Gemini:**
- Claude Sonnet: 5K input + 2K output = $0.045

**With Gemini Delegation:**
- Claude Haiku (orchestration): 500 tokens = $0.0015
- Gemini Flash (analysis): 5K input + 2K output = $0.0021
- **Total: $0.0036** (92% savings!)

### Monthly Quota Impact (Claude Pro)

Claude Pro includes quota for Claude models. By delegating to Gemini:

- **Before**: 100 complex code reviews = significant quota usage
- **After**: 100 orchestration calls (minimal) + Gemini (separate budget)
- **Result**: More Claude quota for file operations and git commands

## Configuration

### Adjust Gemini Model

Edit `src/sohnbot/runtime/gemini_delegate.py`:

```python
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash-exp',  # or 'gemini-1.5-pro' for higher quality
    generation_config=generation_config
)
```

Available models:
- `gemini-2.0-flash-exp`: Fastest, cheapest (recommended)
- `gemini-1.5-pro`: Higher quality, more expensive
- `gemini-1.5-flash`: Balance of speed and quality

### Adjust Max Tokens

In the tool call, Claude can specify:
```python
await delegate_to_gemini(
    prompt="Your prompt",
    max_tokens=8000  # Adjust based on expected response length
)
```

## Monitoring Usage

### View Delegation Logs

```bash
# Check operation logs for Gemini usage
/logs capability=ai limit=50
```

### Cost Tracking

Usage is automatically logged with cost estimates:

```json
{
  "event": "gemini_usage",
  "model": "gemini-2.0-flash-exp",
  "input_tokens": 5000,
  "output_tokens": 2000,
  "estimated_cost_usd": 0.0021
}
```

### Query Logs in Database

```sql
SELECT
    capability,
    action,
    status,
    duration_ms,
    timestamp
FROM execution_log
WHERE capability = 'ai'
ORDER BY timestamp DESC
LIMIT 50;
```

## Best Practices

### 1. Let Claude Decide

Don't manually specify when to use Gemini - Claude will automatically delegate when appropriate based on the task type.

### 2. Monitor Costs

Check logs regularly to understand usage patterns:
```bash
/logs capability=ai
```

### 3. Adjust Model Selection

For routine tasks, keep using Haiku (default):
```bash
/config get models.telegram_default
```

For critical operations, upgrade temporarily:
```bash
/config set models.telegram_default claude-sonnet-4-6
```

### 4. Budget Alerts

Set up budget alerts in Google Cloud Console for Gemini API usage.

### 5. Rate Limiting

Gemini has rate limits. If you hit them frequently, consider:
- Spreading requests over time
- Using scheduled jobs for non-urgent analysis
- Upgrading to paid tier with higher limits

## Troubleshooting

### "GOOGLE_API_KEY environment variable not set"

**Solution:**
1. Verify `.env` file has `GOOGLE_API_KEY=your_key`
2. Restart SohnBot: `poetry run python -m sohnbot`
3. Check logs for confirmation

### "google-generativeai package not installed"

**Solution:**
```bash
poetry add google-generativeai
poetry install
```

### Gemini Delegation Not Being Used

**Possible Causes:**
1. Task requires file operations (Claude handles directly)
2. Google API key not set
3. Gemini SDK not installed

**Debug:**
```bash
# Check if tool is available
/status

# Check recent operations
/logs limit=20
```

### Rate Limit Errors

**Solution:**
1. Check [Google AI Studio quotas](https://aistudio.google.com/app/quotas)
2. Implement request queuing for non-urgent tasks
3. Consider upgrading API tier

## Security Considerations

### API Key Protection

- ✅ Store in `.env` (gitignored)
- ✅ Never commit to version control
- ✅ Use environment variables only
- ❌ Never hardcode in source files

### Data Privacy

- Gemini API processes data on Google's servers
- Review [Google's Privacy Policy](https://policies.google.com/privacy)
- Consider data sensitivity before delegation
- For highly sensitive operations, keep using Claude only

### Prompt Isolation

Claude's delegation maintains context isolation:
- File paths are NOT sent to Gemini
- Only the reasoning prompt is delegated
- SohnBot capabilities remain broker-protected

## FAQs

### Q: Will all requests go to Gemini?

**A:** No. Claude (Haiku) intelligently decides when delegation is beneficial. File operations, git commands, and simple queries stay with Claude.

### Q: Do I need both Claude and Gemini API keys?

**A:** Yes. Claude handles orchestration and SohnBot capabilities. Gemini handles delegated reasoning tasks.

### Q: Can I use only Gemini without Claude?

**A:** No. SohnBot's architecture requires Claude Agent SDK for orchestration and tool use. Gemini is an optional optimization.

### Q: What if Gemini is down?

**A:** Claude will fall back to handling the request directly. The delegation is opportunistic, not required.

### Q: How much will Gemini cost me?

**A:** Gemini 2.0 Flash is very cheap (~$0.075 per 1M input tokens). Most users spend less than $1/month even with heavy usage.

### Q: Can I delegate to other AI providers?

**A:** Currently only Gemini is supported. Adding OpenAI or other providers would require similar integration work.

---

**Version:** 1.0
**Last Updated:** 2026-03-03
**Related:** [README.md](../README.md), [USER_GUIDE.md](USER_GUIDE.md)
