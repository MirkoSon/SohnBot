## Recommended Settings & Rules

### 1. **Permission Configuration**
- **Pre-grant WebFetch permission** — Grant it upfront to eliminate friction when transitioning from search to fetch
- This removes the permission request bottleneck

### 2. **Workflow Triage Rules**

**Use Brave Search first when:**
- Exploring a new topic (need breadth, not depth)
- Finding authoritative sources
- Checking multiple sources exist
- User just wants quick overview + URLs
- Real-time/current information matters

**Use WebFetch after Brave when:**
- You've identified 1-3 most relevant sources
- Need to extract specific data from pages
- Comparing detailed information across sources
- User asks "what does this page say about X?"

### 3. **Hybrid Workflow Rule**
```
For comprehensive queries:
Brave Search (discovery) → Identify top 2-3 results → WebFetch (detail extraction)
```

### 4. **Task-Specific Patterns**

| Task Type | Approach |
|-----------|----------|
| News/current events | Brave fresh mode (real-time) |
| Technical documentation | Brave → WebFetch if needed |
| Product comparisons | Brave (multiple sources) → WebFetch (details) |
| Weather/forecasts | **Bare Search only** (no permission needed, URLs are actionable) |
| Deep research | Brave (breadth) → WebFetch (depth on 2-3 sources) |

### 5. **Optimization Heuristics**
- **Don't fetch every result** — Reduces latency & token usage
- **Use Brave's "fresh" mode** for time-sensitive queries
- **Ask focused questions in WebFetch** to extract only needed data
- **Batch related fetches** to amortize latency

## A skill would be perfect for this because it would:

1. **Encapsulate the hybrid workflow** — Apply the triage rules automatically without code changes
2. **Handle permissions** — WebFetch could be pre-authorized at the skill level
3. **Be reusable** — Invoke with a simple command like `/hybrid-research` or `/web-research`
4. **Stay flexible** — Easy to adjust the workflow without touching the codebase

### Two-Part Solution:

**Part 1 (Simpler):** Just unlock WebFetch permissions globally so both tools work seamlessly

**Part 2 (Better):** Create a research skill that:
- Takes a query and optional depth level ("quick" vs "deep")
- Runs Brave Search first for discovery
- Automatically fetches top 1-2 results for detail extraction
- Returns both high-level overview AND deep findings
- Applies the task-specific rules from our workflow

The skill could be something like:
```
/web-research "weather in Helsinki" --depth=quick
→ Returns: Brave results + actionable URLs

/web-research "best React patterns 2026" --depth=deep  
→ Returns: Brave discovery + WebFetch details from top results
```

**Which would you prefer?**
1. Just unlock WebFetch globally as a quick fix
2. Create the hybrid research skill for a polished workflow
3. Both — unlock WebFetch + build the skill for future use