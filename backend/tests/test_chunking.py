import pytest

from app.chunking import chunk_pages
from app.schemas import PageText


def test_preserves_overlap_and_covers_the_entire_text():
    text = "abcdefghijklmnopqrstuvwxyz"
    chunks = chunk_pages([PageText(page_number=2, text=text)], 10, 3)

    assert [chunk.text for chunk in chunks] == [
        "abcdefghij", "hijklmnopq", "opqrstuvwx", "vwxyz"
    ]
    reconstructed = chunks[0].text + "".join(chunk.text[3:] for chunk in chunks[1:])
    assert reconstructed == text
    assert all(chunk.page_number == 2 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3]


def test_never_combines_pages_and_skips_empty_pages():
    pages = [
        PageText(page_number=1, text="Short page."),
        PageText(page_number=2, text=" \n\t"),
        PageText(page_number=3, text="Next page."),
    ]
    chunks = chunk_pages(pages, 100, 20)
    assert [(chunk.chunk_index, chunk.page_number, chunk.text) for chunk in chunks] == [
        (0, 1, "Short page."), (1, 3, "Next page.")
    ]


@pytest.mark.parametrize("text", ["short", "abcdefghij"])
def test_short_or_exact_size_page_produces_one_chunk(text):
    chunks = chunk_pages([PageText(page_number=1, text=text)], 10, 3)
    assert [chunk.text for chunk in chunks] == [text]


def test_zero_overlap_and_unicode_characters():
    chunks = chunk_pages([PageText(page_number=1, text="étéàôç")], 3, 0)
    assert [chunk.text for chunk in chunks] == ["été", "àôç"]


def test_trims_whitespace_and_skips_whitespace_only_windows():
    chunks = chunk_pages([PageText(page_number=1, text="  abc      def  ")], 3, 0)
    assert [chunk.text for chunk in chunks] == ["abc", "def"]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]


def test_empty_input():
    assert chunk_pages([], 10, 2) == []


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, -1), (10, 10), (10, 11)])
def test_rejects_invalid_parameters(size, overlap):
    with pytest.raises(ValueError):
        chunk_pages([], size, overlap)
