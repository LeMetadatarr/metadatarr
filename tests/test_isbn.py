"""ISBN normalisation + ExternalIds back-fill."""
from metadatarr.resolve import ExternalIds
from mediavocab.text import isbn10_to_13, isbn13_to_10, normalize_isbn


def test_isbn10_to_13_known_pair():
    # The Hobbit, 1991 HarperCollins UK paperback
    assert isbn10_to_13("0261103288") == "9780261103283"


def test_isbn13_to_10_known_pair():
    assert isbn13_to_10("9780261103283") == "0261103288"


def test_isbn10_to_13_handles_x_check_digit():
    # Pretty-printed ISBN-10 with hyphens + 'X' check digit
    assert isbn10_to_13("0-8044-2957-X") is not None


def test_isbn13_to_10_rejects_non_978_prefix():
    # 979-prefixed ISBN-13 has no ISBN-10 form
    assert isbn13_to_10("9791234567896") is None


def test_normalize_isbn_strips_format_noise():
    assert normalize_isbn("978-0-261-10328-3") == "9780261103283"
    assert normalize_isbn("0 261 10328 8") == "0261103288"
    assert normalize_isbn("not-an-isbn") is None
    assert normalize_isbn("") is None


def test_external_ids_backfills_sibling_form():
    e = ExternalIds(isbn_10="0-261-10328-8")
    assert e.isbn_10 == "0261103288"
    assert e.isbn_13 == "9780261103283"

    f = ExternalIds(isbn_13="978-0-261-10328-3")
    assert f.isbn_13 == "9780261103283"
    assert f.isbn_10 == "0261103288"


def test_external_ids_merge_unifies_isbn_variants():
    """A merge between providers that disagree on representation still aligns."""
    a = ExternalIds(isbn_10="0261103288")
    b = ExternalIds(isbn_13="9780261103283")
    out = a.merge(b)
    assert out.isbn_10 == "0261103288"
    assert out.isbn_13 == "9780261103283"
