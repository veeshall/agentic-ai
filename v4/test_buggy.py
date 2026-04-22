from buggy import merge_dicts

def test_merge_returns_combined():
    result = merge_dicts({"a": 1}, {"b": 2})
    assert result == {"a": 1, "b": 2}

def test_merge_updates_override():
    result = merge_dicts({"a": 1, "b": 1}, {"b": 2})
    assert result == {"a": 1, "b": 2}

def test_merge_does_not_mutate_original():
    original = {"a": 1}
    merge_dicts(original, {"b": 2})
    assert original == {"a": 1}, f"original was mutated: {original}"
