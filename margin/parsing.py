"""Turns an uploaded file into pages of plain text."""
import io
import re
from dataclasses import dataclass

from pypdf import PdfReader

MAX_PDF_PAGES = 500
ALLOWED = {".pdf": "pdf", ".md": "md", ".markdown": "md", ".txt": "txt"}


class UnsupportedFile(ValueError):
    pass


@dataclass
class Parsed:
    title: str
    kind: str
    pages: list[str]  # one entry per PDF page; a single entry for text and Markdown


def parse(filename: str, data: bytes) -> Parsed:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = ALLOWED.get(ext)
    if kind is None:
        raise UnsupportedFile("Only PDF, Markdown and plain-text files are supported")

    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            raise UnsupportedFile("This file says it's a PDF but isn't one")
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UnsupportedFile("Password-protected PDFs can't be read")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise UnsupportedFile(f"PDFs can have up to {MAX_PDF_PAGES} pages")
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
        if not any(pages):
            raise UnsupportedFile("No text found. Scanned PDFs need OCR first")
        title = (reader.metadata.title if reader.metadata and reader.metadata.title else None) or _title_from_name(filename)
        return Parsed(title=title.strip()[:200], kind=kind, pages=pages)

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise UnsupportedFile("Text files must be UTF-8") from e
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise UnsupportedFile("The file is empty")
    heading = re.search(r"^#\s+(.+)$", text, re.M) if kind == "md" else None
    title = heading.group(1).strip() if heading else _title_from_name(filename)
    return Parsed(title=title[:200], kind=kind, pages=[text])


def _title_from_name(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    return re.sub(r"[-_]+", " ", stem).strip().capitalize() or "Untitled"
