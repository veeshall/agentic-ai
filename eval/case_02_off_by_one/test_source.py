from source import first_n

def test_first_n_basic():
    assert first_n([1, 2, 3, 4, 5], 3) == [1, 2, 3]

def test_first_n_all():
    assert first_n([1, 2, 3], 3) == [1, 2, 3]

def test_first_n_one():
    assert first_n([1, 2, 3], 1) == [1]
