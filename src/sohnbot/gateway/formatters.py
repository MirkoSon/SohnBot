"""
Telegram message formatting utilities.

Handles splitting long responses and formatting for Telegram's constraints.
"""


def format_for_telegram(response: str, max_length: int = 4096) -> list[str]:
    """
    Split long responses for Telegram's 4096-character limit.

    Args:
        response: The response text to format
        max_length: Maximum length per message (default: 4096)

    Returns:
        List of message chunks, each under max_length characters

    Examples:
        >>> format_for_telegram("Short message")
        ['Short message']

        >>> long_msg = "\\n".join(["Line " + str(i) for i in range(200)])
        >>> chunks = format_for_telegram(long_msg)
        >>> all(len(chunk) <= 4096 for chunk in chunks)
        True
    """
    if len(response) <= max_length:
        return [response]

    messages = []
    current = ""

    # Split on newlines to preserve formatting
    for line in response.split("\n"):
        # If adding this line would exceed the limit
        if len(current) + len(line) + 1 > max_length:
            # Save current chunk if not empty
            if current:
                messages.append(current)
            # Start new chunk with this line
            current = line
        else:
            # Add line to current chunk
            current += "\n" + line if current else line

    # Don't forget the last chunk
    if current:
        messages.append(current)

    return messages
