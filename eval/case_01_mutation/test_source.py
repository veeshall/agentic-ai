from source import merge_dicts

def test_merge_returns_combined():
    assert merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

def test_merge_override():
    assert merge_dicts({"a": 1}, {"a": 99}) == {"a": 99}

def test_does_not_mutate_original():
    base = {"a": 1}
    merge_dicts(base, {"b": 2})
    assert base == {"a": 1}
