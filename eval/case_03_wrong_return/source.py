def is_palindrome(s):
    """Return True if s is a palindrome."""
    cleaned = s.lower().replace(" ", "")
    return cleaned == cleaned
