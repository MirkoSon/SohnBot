# Claude Skill: SohnBot Web Research

Use this skill for web research tasks where breadth + depth are both needed.

## Goal
- Start with broad discovery.
- Fetch details from only the most relevant sources.
- Return concise synthesis with cited URLs.

## Tooling
- Primary tool: `mcp__sohnbot__web__research`
- Fallback tool: `mcp__sohnbot__web__search`

## Invocation Pattern
1. If user asks for a quick answer:
   - Call `mcp__sohnbot__web__research` with `depth="quick"` and `mode="fresh"` (or `static` for non-time-sensitive topics).
2. If user asks for detailed comparison/research:
   - Call `mcp__sohnbot__web__research` with `depth="deep"` and `mode="fresh"` unless topic is clearly static.
3. If research call fails:
   - Fall back to `mcp__sohnbot__web__search` and surface top links with a short explanation.

## Response Style
- Provide:
  - Short synthesis (2-5 bullets)
  - Source URLs used
  - Any uncertainty/fetch failures

