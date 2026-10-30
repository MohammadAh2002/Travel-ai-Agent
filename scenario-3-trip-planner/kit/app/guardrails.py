from __future__ import annotations

import re


INJECTION_PATTERNS = re.compile(
    r"(ignore (all |the )?(previous|prior) instructions|reveal (the )?(system prompt|secrets)|"
    r"follow these instructions instead|disregard your rules)", re.I
)
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", re.I)
RAW_URL = re.compile(r"https?://[^\s<>)]+", re.I)


def inspect_input(message: str) -> str | None:
    if len(message) > 5000:
        return "Please keep a message under 5,000 characters."
    if INJECTION_PATTERNS.search(message):
        return ("I can help with travel planning, but I’ll ignore instructions that try to override my "
                "travel-safety rules. What would you like to plan?")
    return None


def safe_reply(reply: str, allowed_urls: set[str] | None = None) -> str:
    reply = reply.strip()
    reply = re.sub(r"\b(I booked|I purchased|reservation confirmed)\b", "I cannot book or purchase; ", reply, flags=re.I)
    allowed_urls = allowed_urls or set()
    reply = MARKDOWN_LINK.sub(lambda match: match.group(0) if match.group(2) in allowed_urls else match.group(1), reply)
    reply = RAW_URL.sub(lambda match: match.group(0) if match.group(0).rstrip(".,") in allowed_urls else
                        "[unverified link removed]", reply)
    return reply[:12000]


def untrusted_listing(item: dict) -> dict:
    return {**item, "_data_is_untrusted": True}
