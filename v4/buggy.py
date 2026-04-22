def merge_dicts(base, updates):
    """Merge updates into base, returning a new dict without modifying the original."""
    result = dict(base)
    result.update(updates)
    return result
