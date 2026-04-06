"""Common helper functions."""
import hashlib


def md5_hash(text: str) -> str:
    """Generate MD5 hex digest of text."""
    return hashlib.md5(text.encode()).hexdigest()


def truncate(text: str, max_length: int) -> str:
    """Truncate text to max_length characters."""
    if not text:
        return ""
    return text[:max_length] if len(text) > max_length else text
