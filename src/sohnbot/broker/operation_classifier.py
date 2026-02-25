"""Operation risk classification (Tier 0/1/2/3)."""


def classify_tier(capability: str, action: str, file_count: int) -> int:
    """
    Classify operation into risk tier (0/1/2/3).

    Tier 0: Read-only operations (no state changes)
    Tier 1: Single-file modifications (automatic snapshot)
    Tier 2: Multi-file modifications (comprehensive snapshot)
    Tier 3: Destructive operations (explicit confirmation required, post-MVP)

    Args:
        capability: Capability module (fs, git, sched, web, profiles)
        action: Operation action (read, patch, commit, etc.)
        file_count: Number of files affected by operation

    Returns:
        Tier classification (0, 1, 2, or 3)
    """
    # Tier 0: Read-only operations (no state changes)
    READ_ONLY_ACTIONS = {
        ("fs", "read"),
        ("fs", "list"),
        ("fs", "search"),
        ("git", "status"),
        ("git", "diff"),
        ("web", "search"),
        ("profiles", "lint"),  # Read-only execution
    }
    if (capability, action) in READ_ONLY_ACTIONS:
        return 0

    # Tier 1: Single-file modifications (automatic snapshot)
    SINGLE_FILE_ACTIONS = {
        ("fs", "apply_patch"),  # Single-file patch
        ("git", "commit"),  # Commit after validation
        ("git", "checkout"),  # Branch switching (for rollback)
    }
    if (capability, action) in SINGLE_FILE_ACTIONS and file_count == 1:
        return 1

    # Tier 2: Multi-file modifications (comprehensive snapshot)
    if file_count > 1:
        return 2

    # Tier 3: Destructive operations (future, requires confirmation)
    # Reserved for post-MVP features (file deletion, repository reset, etc.)

    # Default to Tier 2 for unknown operations (conservative)
    return 2
