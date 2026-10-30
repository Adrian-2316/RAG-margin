"""Splits documents into passages that are small enough to cite and big enough to make sense alone."""
import re
from dataclasses import dataclass

TARGET_CHARS = 900
MAX_CHARS = 1400


@dataclass
class Piece:
    heading: str
    text: str
    page: int | None


def chunk_markdown(text: str, title: str) -> list[Piece]:
    """Follows the heading structure, so each passage carries its section path (Handbook › Holidays)."""
    pieces: list[Piece] = []
    path: list[str] = []
    body: list[str] = []

    def flush():
        if body:
            heading = " › ".join([title, *path[1:]] if path and path[0] == title else [title, *path])
            pieces.extend(Piece(heading, t, None) for t in _pack("\n".join(body)))
            body.clear()

    for line in text.split("\n"):
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = path[: level - 1] + [m.group(2).strip()]
        else:
            body.append(line)
    flush()
    return pieces


def chunk_pages(pages: list[str], title: str) -> list[Piece]:
    out: list[Piece] = []
    for number, page in enumerate(pages, start=1):
        out.extend(Piece(f"{title} › page {number}", t, number) for t in _pack(page))
    return out


def _pack(text: str) -> list[str]:
    """Groups paragraphs up to the target size. A table or list stays in one passage where it fits."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    current = ""
    for p in paragraphs:
        for part in _split_long(p):
            if current and len(current) + len(part) + 2 > TARGET_CHARS:
                out.append(current)
                current = part
            else:
                current = f"{current}\n\n{part}" if current else part
    if current:
        out.append(current)
    return out


def _split_long(paragraph: str) -> list[str]:
    if len(paragraph) <= MAX_CHARS:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    parts, current = [], ""
    for s in sentences:
        while len(s) > MAX_CHARS:  # a run-on line with no sentence breaks
            parts.append(s[:MAX_CHARS])
            s = s[MAX_CHARS:]
        if current and len(current) + len(s) + 1 > MAX_CHARS:
            parts.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        parts.append(current)
    return parts
