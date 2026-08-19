from src.slug import slugify, unique_slug

def test_transliteration():
    assert slugify("Café déjà vu") == "cafe-deja-vu"

def test_mixed_accents_numbers():
    assert slugify("Über-cool 2026: Año Nuevo!") == "uber-cool-2026-ano-nuevo"

def test_cjk_dropped():
    assert slugify("日本語 guide") == "guide"

def test_all_dropped_falls_back():
    assert unique_slug("日本語", set()) == "untitled"

def test_collapse_and_trim():
    assert slugify("  --Hello---World--  ") == "hello-world"

def test_unique_counter():
    assert unique_slug("Café", {"cafe", "cafe-2"}) == "cafe-3"
