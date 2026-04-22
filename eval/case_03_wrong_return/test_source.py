from source import is_palindrome

def test_palindrome_true():
    assert is_palindrome("racecar") == True

def test_palindrome_with_spaces():
    assert is_palindrome("race car") == True

def test_not_palindrome():
    assert is_palindrome("hello") == False
