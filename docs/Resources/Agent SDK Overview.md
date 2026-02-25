# Claude Agent SDK — Overview

Build production AI agents with Claude Code as a library.

> The Claude Code SDK has been renamed to the Claude Agent SDK.  
> If you're migrating from the old SDK, see the Migration Guide.

---

## What Is the Agent SDK?

The Claude Agent SDK allows you to build AI agents that can:

- Read files
- Run commands
- Search the web
- Edit code
- Manage context
- Operate autonomously using a built-in agent loop

It provides the same tools and context management that power Claude Code, programmable in **Python** and **TypeScript**.

---

## Quick Example (Python)

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    async for message in query(
        prompt="Find and fix the bug in auth.py",
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Bash"]
        ),
    ):
        print(message)

asyncio.run(main())
```

Claude reads the file, finds the bug, and edits it automatically.

---

## Built-in Tools

| Tool            | Description                                |
| --------------- | ------------------------------------------ |
| Read            | Read any file in the working directory     |
| Write           | Create new files                           |
| Edit            | Make precise edits to existing files       |
| Bash            | Run terminal commands and git operations   |
| Glob            | Find files by pattern                      |
| Grep            | Search file contents using regex           |
| WebSearch       | Search the web for current information     |
| WebFetch        | Fetch and parse web page content           |
| AskUserQuestion | Ask user clarifying questions with options |

---

## Installation

### TypeScript

```bash
npm install @anthropic-ai/claude-agent-sdk
```

### Python

```bash
pip install claude-agent-sdk
```

---

## Authentication

Set your API key:

```bash
export ANTHROPIC_API_KEY=your-api-key
```

The SDK also supports authentication via:

* Amazon Bedrock
  `CLAUDE_CODE_USE_BEDROCK=1`

* Google Vertex AI
  `CLAUDE_CODE_USE_VERTEX=1`

* Microsoft Azure Foundry
  `CLAUDE_CODE_USE_FOUNDRY=1`

> Anthropic does not allow third-party developers to offer claude.ai login or rate limits. Use API key authentication instead.

---

## Example: List Files

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    async for message in query(
        prompt="What files are in this directory?",
        options=ClaudeAgentOptions(
            allowed_tools=["Bash", "Glob"]
        ),
    ):
        if hasattr(message, "result"):
            print(message.result)

asyncio.run(main())
```

---

## Filesystem-Based Configuration

The SDK supports Claude Code-style filesystem configuration:

* `.claude/skills/SKILL.md`
* `.claude/commands/*.md`
* `CLAUDE.md`
* Plugins via programmatic configuration

Enable via:

* `setting_sources=["project"]` (Python)
* `settingSources: ['project']` (TypeScript)

---

## Agent SDK vs Client SDK

### Client SDK

* You implement the tool loop manually.
* You handle `stop_reason == "tool_use"` responses.
* You execute tools yourself.

Example:

```python
response = client.messages.create(...)
while response.stop_reason == "tool_use":
    result = your_tool_executor(response.tool_use)
    response = client.messages.create(tool_result=result, **params)
```

### Agent SDK

* Claude autonomously handles tool execution.
* You iterate over streamed messages.

```python
async for message in query(prompt="Fix the bug in auth.py"):
    print(message)
```

---

## Branding Guidelines

Allowed:

* "Claude Agent"
* "Claude"
* "{YourAgentName} Powered by Claude"

Not allowed:

* "Claude Code"
* "Claude Code Agent"
* Claude Code ASCII branding

---