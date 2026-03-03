# SohnBot User Guide

Welcome to SohnBot! This guide will help you get started and make the most of your autonomous execution assistant.

## What is SohnBot?

SohnBot is your personal autonomous agent that can:
- 🔍 Search and read files in your project
- ✏️ Edit files with patches (with automatic git snapshots for safety)
- 📊 Monitor system health and status
- ⏰ Schedule automated tasks
- 🌐 Search the web for information
- 📝 Execute git operations
- 🛡️ All operations are policy-enforced for safety

## Getting Started

### 1. First Contact

Once SohnBot is running, find it on Telegram and send:
```
/help
```

This shows all available commands.

### 2. Enable Notifications

Get notified when operations complete:
```
/notify on
```

Check notification status:
```
/notify status
```

### 3. Check System Health

See if everything is running smoothly:
```
/health
```

---

## Available Commands

### `/help` - Show Available Commands
```
/help
```
Displays a list of all commands and their usage.

---

### `/notify` - Manage Notifications
Control whether you receive notifications when operations complete.

**Enable notifications:**
```
/notify on
```

**Disable notifications:**
```
/notify off
```

**Check status:**
```
/notify status
```

---

### `/status` - View System Status
Get a snapshot of the current system state.

```
/status
```

Shows:
- Active operations in progress
- Recent operations
- Scheduler next runs
- System resource usage

---

### `/health` - Check System Health
View detailed health checks for all system components.

```
/health
```

Provides:
- Database connectivity status
- File system access
- External dependencies (git, ripgrep)
- Overall health score

---

### `/logs` - Query Operation Logs
Search and filter execution logs.

**View recent logs:**
```
/logs
```

**Filter by status:**
```
/logs status=completed
/logs status=failed
```

**Filter by capability:**
```
/logs capability=fs
/logs capability=git
/logs capability=scheduler
```

**Limit results:**
```
/logs limit=20
```

**Combine filters:**
```
/logs status=completed capability=fs limit=10
```

---

### `/config` - View and Update Configuration
Manage dynamic configuration settings (changes apply immediately without restart).

**List all configuration keys:**
```
/config list
```

**List only dynamic (hot-reloadable) keys:**
```
/config list dynamic
```

**List only static (requires restart) keys:**
```
/config list static
```

**Get a specific value:**
```
/config get logging.level
```

**Set a value:**
```
/config set logging.level DEBUG
/config set files.search_timeout_seconds 10
```

**Common settings:**
- `logging.level` - Log verbosity (DEBUG, INFO, WARNING, ERROR)
- `files.search_timeout_seconds` - Search operation timeout
- `notifications.{chat_id}.enabled` - Per-chat notification toggle

---

### `/schedule` - Manage Scheduled Jobs
Create and manage automated tasks that run on a schedule.

**List all jobs:**
```
/schedule list
```

**Create a new job:**
```
/schedule create --name daily-backup --cron "0 2 * * *" --action snapshot_health --timezone America/New_York
```

**Job parameters:**
- `--name` - Unique job identifier
- `--cron` - Cron expression (when to run)
- `--action` - What to do (e.g., `snapshot_health`, `prune_snapshots`)
- `--timezone` - Timezone for schedule (e.g., `America/New_York`, `Europe/London`, `UTC`)

**Common cron expressions:**
- `0 * * * *` - Every hour
- `0 9 * * *` - Daily at 9 AM
- `0 9 * * 1` - Every Monday at 9 AM
- `*/15 * * * *` - Every 15 minutes
- `0 0 1 * *` - First day of each month

**Enable/disable a job:**
```
/schedule enable daily-backup
/schedule disable daily-backup
```

**Delete a job:**
```
/schedule delete daily-backup
```

**View job details:**
```
/schedule info daily-backup
```

---

### `/heartbeat` - Configure Daily Heartbeat
Set up a daily health check notification.

**Enable heartbeat:**
```
/heartbeat enable --time 09:00 --timezone America/New_York
```

**Check heartbeat status:**
```
/heartbeat status
```

**Disable heartbeat:**
```
/heartbeat disable
```

---

## Natural Language Requests

Beyond commands, you can ask SohnBot to do things in natural language!

### File Operations

**Search for code:**
```
Search for "def calculate_total" in the src directory
Find files containing "API_KEY"
```

**Read files:**
```
Read the README.md file
Show me the contents of config/settings.py
```

**List files:**
```
List all Python files in src/
Show files in the tests directory
```

**Edit files (creates automatic git snapshot):**
```
Apply this patch to src/main.py:
[paste your unified diff patch]
```

### Git Operations

**Check status:**
```
Show git status for this repository
What files have changed?
```

**View diffs:**
```
Show me the diff of uncommitted changes
What changed in src/app.py?
```

**Create commits:**
```
Create a commit with message "Fix: Update error handling"
Commit these changes: [list of files]
```

**View snapshots:**
```
List all snapshots
Show available rollback points
```

**Rollback changes:**
```
Rollback to snapshot snapshot/edit-2026-03-03-1430
```

### Web Search

**Search the web:**
```
Search the web for "Python async best practices"
Find recent articles about TypeScript 5.0
```

---

## Safety Features

SohnBot is designed with safety first:

### 🛡️ Scope Validation
- All file operations are restricted to allowed directories
- Attempts to access files outside scope are blocked
- Path traversal attacks (../, etc.) are prevented

### 📸 Automatic Snapshots
- File edits automatically create git snapshot branches
- Snapshots are named: `snapshot/edit-YYYY-MM-DD-HHMM`
- Easy rollback if something goes wrong

### 🔐 Operation Tiers
- **Tier 0** - Read-only operations (safe)
- **Tier 1** - Modifications with snapshots
- **Tier 2** - Administrative operations

### 📋 Audit Trail
- Every operation is logged to SQLite database
- View history with `/logs`
- Includes correlation IDs for request tracing

### ⏱️ Timeouts
- All operations have configurable timeouts
- Prevents runaway processes
- Subprocess trees are properly terminated

---

## Troubleshooting

### "Operation denied: Path outside allowed scope"
The file or directory you're trying to access is outside the configured allowed scope. Check your `config/default.toml` for `scope.allowed_roots`.

### "git CLI is required for snapshot operations"
Git is not installed or not in your PATH. Install Git and ensure it's accessible from the command line.

### "ripgrep (rg) is required for search operations"
Ripgrep is not installed. Install it:
- macOS: `brew install ripgrep`
- Ubuntu: `sudo apt-get install ripgrep`
- Windows: `choco install ripgrep`

### Notifications not arriving
1. Check if notifications are enabled: `/notify status`
2. Enable them: `/notify on`
3. Check system health: `/health`

### Operation timed out
Some operations may need longer timeouts. Update configuration:
```
/config set files.search_timeout_seconds 30
```

### Database locked errors
Only one operation can write to the database at a time. This is normal for concurrent operations. The system will retry automatically.

---

## Best Practices

### 1. Use Notifications Wisely
- Enable notifications for important operations
- Disable during bulk operations to avoid spam

### 2. Regular Health Checks
Run `/health` periodically to catch issues early.

### 3. Review Logs
Use `/logs status=failed` to identify and fix recurring issues.

### 4. Snapshot Management
List snapshots periodically and prune old ones:
```
List all snapshots in /path/to/repo
```

### 5. Schedule Maintenance
Create scheduled jobs for:
- Daily health snapshots
- Weekly snapshot pruning
- Regular backups

### 6. Monitor Scheduled Jobs
Check job status regularly:
```
/schedule list
```

---

## Privacy & Security

- **API Keys**: Never stored in plaintext; use environment variables
- **Local Execution**: All operations run on your machine
- **No Cloud Storage**: Data stays local (SQLite database)
- **Telegram Encryption**: Uses Telegram's end-to-end encryption
- **Process Isolation**: Subprocess trees are properly terminated
- **Input Validation**: All user inputs are validated and sanitized

---

## Getting Help

### In-Bot Help
```
/help
```

### Check System Status
```
/health
/status
```

### View Recent Activity
```
/logs limit=20
```

### Developer Documentation
See `docs/` folder for:
- `PRD.md` - Product requirements
- `development_environment.md` - Developer setup
- Architecture documentation

---

## Quick Reference Card

| Command | Purpose |
|---------|---------|
| `/help` | Show all commands |
| `/notify on\|off\|status` | Manage notifications |
| `/status` | View system status |
| `/health` | Check system health |
| `/logs [filters]` | Query operation logs |
| `/config list\|get\|set` | Manage configuration |
| `/schedule list\|create\|delete` | Manage scheduled jobs |
| `/heartbeat enable\|disable\|status` | Daily health check |

---

**Version:** 1.0
**Last Updated:** 2026-03-03
**Questions?** Check `/help` or review the logs with `/logs`
