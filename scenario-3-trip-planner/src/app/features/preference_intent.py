import re


def is_preference_save(message: str) -> bool:
    """Recognize explicit requests to remember personal travel preferences."""
    return bool(re.match(
        r"^(?:(?:please|can you|could you)\s+)?"
        r"(?:remember\s+(?:that\b|for\s+future\s+trips\b|my\b|i\b)|"
        r"(?:save|store)\s+my\s+(?:travel\s+)?preferences\b|"
        r"(?:تذكر|تذكّر|احفظ|احفظلي|خزن|خزّن)\s)",
        message.strip(), re.I,
    ))
