# Claude-to-Gemini Failover System

## Overview

SohnBot implements an **automatic failover system** that switches from Claude to Gemini when Claude hits rate limits or quota exhaustion. This ensures continuous operation even when your Claude subscription reaches its limits.

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                     User sends message                       │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │   MessageRouter     │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │   AgentSelector     │
                └──────────┬──────────┘
                           │
           ┌───────────────┴───────────────┐
           │                               │
           ▼                               ▼
    ┌─────────────┐                ┌─────────────────┐
    │   Claude    │                │ Gemini Fallback │
    │  (Primary)  │                │   (Backup)      │
    └──────┬──────┘                └────────┬────────┘
           │                                 │
           │ Rate Limit Error                │
           └────────────┐                    │
                        │                    │
                        ▼                    │
              ┌──────────────────┐           │
              │ Mark Failover    │           │
              │ Notify User      │           │
              │ Switch to Gemini │───────────┘
              └──────────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │ Health Check     │
              │ Every 5 minutes  │
              └──────────────────┘
                        │
                        │ Claude Available
                        ▼
              ┌──────────────────┐
              │ Switch Back      │
              │ Notify User      │
              └──────────────────┘
```

## Features

### 1. Automatic Detection
- Detects Claude rate limit errors automatically
- Monitors for quota exhaustion
- Tracks failure patterns

### 2. Seamless Failover
- Switches to Gemini immediately
- Notifies user about mode change
- Continues conversation without interruption

### 3. Limited Capabilities in Fallback
When in Gemini fallback mode:

**✅ Available:**
- Conversations and Q&A
- Code analysis and review
- Document summarization
- Research and explanations
- General reasoning tasks

**❌ Unavailable:**
- File operations (read/write/edit)
- Git commands (status/commit/rollback)
- Scheduled job management
- Web search (Brave API)
- System health checks

### 4. Auto-Recovery
- Checks Claude health every 5 minutes
- Automatically switches back when available
- Notifies user of recovery

### 5. Status Tracking
- `/agent` command shows current mode
- Displays failure reason
- Shows estimated recovery time
- Tracks failure count

## Usage

### Check Current Agent Mode

```bash
/agent
```

**Response when Claude is active:**
```
✅ Claude Agent active (full capabilities)
```

**Response in fallback mode:**
```
⚠️ **Gemini Fallback Mode Active**

**Reason**: Rate limit exceeded (429)
**Since**: 2026-03-03 14:30:00
**Failures**: 1

**Limited Capabilities**:
- ✅ Conversations and questions
- ✅ Code analysis
- ❌ File operations (read/write)
- ❌ Git commands
- ❌ Scheduled jobs
- ❌ Web search

**Estimated Claude Recovery**: ~22 hours

💡 I'll automatically switch back when Claude is available.
💡 Checking Claude health every 5 minutes.
```

### What Happens During Failover

**1. User sends message**
```
"Read the README.md file"
```

**2. Claude hits rate limit**
```
Error: Rate limit exceeded (429)
```

**3. System switches to Gemini**
```
⚠️ **Claude Rate Limit Reached**

Switching to Gemini fallback mode...

[Status message shown above]
```

**4. Gemini responds**
```
I'm currently in fallback mode and don't have access to file
operations. Claude's rate limit has been reached, so I can't
read files right now.

However, I can help you with:
- Answering questions about your code
- Explaining concepts
- Code review if you paste the content
- General programming advice

The system will automatically switch back to Claude when the
quota resets (estimated: ~22 hours).
```

### When Claude Recovers

**Automatic notification:**
```
✅ **Claude Agent Recovered**

Full capabilities restored! You can now use:
- File operations
- Git commands
- Scheduled jobs
- Web search
- All MCP tools
```

## Configuration

### Environment Variables

```bash
# Required for failover to work
GOOGLE_API_KEY=your_google_api_key

# Or use GEMINI_API_KEY
GEMINI_API_KEY=your_gemini_api_key
```

### Failover Behavior Settings

Currently hardcoded (can be made configurable):

```python
# Health check interval in fallback mode
HEALTH_CHECK_INTERVAL = 5  # minutes

# Estimated quota reset time
QUOTA_RESET_ESTIMATE = 24  # hours (for daily quota)
```

## Monitoring

### View Failover Events in Logs

```bash
/logs capability=runtime limit=50
```

**Look for:**
- `claude_failover_activated` - Failover triggered
- `claude_health_check_started` - Recovery check
- `claude_health_check_passed` - Recovery successful
- `claude_recovery_successful` - Back to Claude

### Check Agent Status

```bash
/agent
```

Shows:
- Current mode (Claude or Gemini fallback)
- Failure reason if in fallback
- Time since failover
- Estimated recovery time
- Capability differences

## Error Scenarios

### Scenario 1: Claude Rate Limit

**Trigger:**
```
Error: Rate limit exceeded (429)
```

**Response:**
- Switch to Gemini immediately
- Notify user
- Check Claude health every 5 minutes
- Auto-recover when available

### Scenario 2: Both Claude and Gemini Fail

**Trigger:**
```
Claude: Rate limit exceeded
Gemini: API key invalid
```

**Response:**
```
❌ **Both Claude and Gemini are currently unavailable**

Claude: Rate limit exceeded (429)
Gemini: Invalid API key

Please try again later.
```

**Action:** Fix Gemini API key and restart

### Scenario 3: Gemini API Key Missing

**When failover triggers:**
```
⚠️ **Claude Rate Limit Reached**

Gemini fallback failed: GOOGLE_API_KEY environment variable not set

Please add GOOGLE_API_KEY to .env and restart SohnBot.
```

## Best Practices

### 1. Set Up Gemini as Backup

Always configure Gemini API key even if you don't plan to use it actively:

```bash
# .env
GOOGLE_API_KEY=your_key_here
```

This ensures failover works when needed.

### 2. Monitor Usage

Check which agent is active regularly:
```bash
/agent
```

### 3. Plan for Limited Capabilities

If Claude hits limits frequently:
- Schedule important file operations during low-usage times
- Use Gemini proactively for code analysis (via delegation)
- Consider upgrading Claude subscription tier

### 4. Test Failover

You can manually test by:
1. Setting invalid Claude credentials temporarily
2. Verifying Gemini takes over
3. Restoring Claude credentials
4. Verifying auto-recovery

### 5. Set Budget Alerts

Set up quota alerts in:
- **Claude**: Monitor usage in Anthropic Console
- **Gemini**: Set budget alerts in Google Cloud Console

## Technical Details

### Rate Limit Detection

The system detects Claude rate limits by checking for:

```python
def is_claude_rate_limit_error(error: Exception) -> bool:
    """Check if error indicates Claude rate limit/quota exhaustion."""
    error_str = str(error).lower()

    indicators = [
        "rate_limit",
        "rate limit",
        "quota",
        "too many requests",
        "429",
        "overloaded",
        "capacity",
    ]

    return any(indicator in error_str for indicator in indicators)
```

### Health Check Implementation

```python
async def check_claude_health():
    """Simple health check with test query."""
    try:
        async for msg in agent_session.query(
            prompt="Health check: respond with OK",
            chat_id="health_check",
            skip_ambiguity_check=True
        ):
            pass  # Just need to complete without error

        # Success - Claude is back
        return True

    except Exception:
        # Still rate limited
        return False
```

### State Management

Agent state is tracked globally:

```python
class AgentStatus:
    current_mode: AgentMode  # CLAUDE or GEMINI_FALLBACK
    claude_last_error: str | None
    claude_last_error_time: datetime | None
    claude_failure_count: int
    last_health_check: datetime | None
    quota_reset_estimate: datetime | None
```

## Troubleshooting

### Failover Not Activating

**Symptom:** Claude errors but doesn't switch to Gemini

**Causes:**
1. Error not detected as rate limit
2. Gemini not configured

**Solution:**
```bash
# Check logs
/logs capability=runtime

# Verify Gemini setup
echo $GOOGLE_API_KEY

# Test Gemini directly
python -c "import google.generativeai as genai; genai.configure(api_key='your_key'); print('OK')"
```

### Stuck in Fallback Mode

**Symptom:** Won't switch back to Claude even after quota reset

**Causes:**
1. Health check still failing
2. Clock skew in quota reset estimate

**Solution:**
```bash
# Check agent status
/agent

# Restart SohnBot (forces fresh check)
poetry run python -m sohnbot
```

### Gemini Fallback Not Working

**Symptom:** Failover fails, both agents unavailable

**Check:**
1. `GOOGLE_API_KEY` in `.env`
2. `google-generativeai` installed: `poetry show google-generativeai`
3. API key valid: Test at https://aistudio.google.com/

**Fix:**
```bash
# Install if missing
poetry add google-generativeai

# Update .env with valid key
GOOGLE_API_KEY=your_valid_key

# Restart
poetry run python -m sohnbot
```

## Future Enhancements

Potential improvements:

1. **Configurable health check interval**
   - Allow user to set check frequency

2. **Smart quota estimation**
   - Learn from actual reset times
   - Adjust estimates based on patterns

3. **Proactive quota monitoring**
   - Warn before hitting limits
   - Suggest switching to Gemini delegation

4. **Multi-tier fallback**
   - Primary: Claude Sonnet
   - Secondary: Claude Haiku
   - Tertiary: Gemini

5. **Capability-specific fallback**
   - Keep file operations queued
   - Only conversations switch to Gemini

---

**Version:** 1.0
**Last Updated:** 2026-03-03
**Related:** [GEMINI_INTEGRATION.md](GEMINI_INTEGRATION.md), [README.md](../README.md)
