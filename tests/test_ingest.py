import pytest

from margin.chunking import MAX_CHARS as MAX, chunk_markdown, chunk_pages
from margin.parsing import UnsupportedFile, parse
from tests.conftest import make_pdf


def test_markdown_chunks_follow_headings():
    text = "# Handbook\n\nIntro line.\n\n## Holidays\n\n25 days a year.\n\n## Sick leave\n\nNote from day 4."
    pieces = chunk_markdown(text, "Handbook")
    headings = [p.heading for p in pieces]
    assert "Handbook › Holidays" in headings and "Handbook › Sick leave" in headings
    assert any("25 days" in p.text for p in pieces if p.heading == "Handbook › Holidays")


def test_long_sections_are_split_but_no_text_is_lost():
    para = " ".join(f"Sentence number {i} is here." for i in range(400))
    pieces = chunk_markdown(f"# T\n\n## Long\n\n{para}", "T")
    assert len(pieces) > 1
    assert all(len(p.text) <= MAX for p in pieces)
    assert "Sentence number 399" in " ".join(p.text for p in pieces)


def test_pdf_pages_keep_their_page_number():
    parsed = parse("policy.pdf", make_pdf(["Refunds within 30 days.", "Keep the receipt."]))
    assert parsed.kind == "pdf"
    assert "Refunds within 30 days." in parsed.pages[0]
    pieces = chunk_pages(parsed.pages, parsed.title)
    assert pieces[0].page == 1


def test_title_comes_from_the_first_markdown_heading():
    assert parse("x.md", b"# Opening checklist\n\nLights on.").title == "Opening checklist"
    assert parse("closing_rota.txt", b"Lights off.").title == "Closing rota"


@pytest.mark.parametrize("name,data,message", [
    ("evil.exe", b"MZ...", "Only PDF"),
    ("fake.pdf", b"<html>not a pdf</html>", "isn't one"),
    ("latin1.txt", "café".encode("latin-1"), "UTF-8"),
    ("empty.md", b"   \n", "empty"),
    ("noext", b"hello", "Only PDF"),
])
def test_rejects_files_it_cannot_read(name, data, message):
    with pytest.raises(UnsupportedFile, match=message):
        parse(name, data)
