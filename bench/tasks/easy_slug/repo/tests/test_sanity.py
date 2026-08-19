from src.slug import slugify, unique_slug

def test_basic():
    assert slugify("Hello, World!") == "hello-world"

def test_unique():
    assert unique_slug("Hello", {"hello"}) == "hello-2"
