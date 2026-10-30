import re

import pytest
from fastapi.testclient import TestClient

from margin.config import Settings
from margin.main import create_app

AUTH = ("reader", "test-password")
WRITE = {"X-Requested-With": "margin"}

# A few words that mean the same thing, so the fake embedder can show what semantic search adds.
SYNONYMS = {"vacation": "holiday", "leave": "holiday", "pto": "holiday", "annual": "holiday"}


class FakeEmbedder:
    """Deterministic bag-of-words vectors, with synonyms folded together."""

    name = "fake"
    dim = 256

    def embed(self, texts, kind):
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for w in re.findall(r"[a-z]+", text.lower()):
                w = SYNONYMS.get(w, w)
                v[hash(w) % self.dim] += 1.0
            out.append(v)
        return out


def make_pdf(lines: list[str]) -> bytes:
    """A minimal one-page PDF with real text, built by hand so the tests need no PDF writer."""
    text = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body, offsets = "%PDF-1.4\n", []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n{obj}\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    body += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return body.encode("latin-1")


def settings(tmp_path, **overrides) -> Settings:
    return Settings(_env_file=None, database_url=f"sqlite:///{tmp_path}/margin.db", margin_password=AUTH[1],
                    anthropic_api_key=None, voyage_api_key=None, **overrides)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as c:
        yield c


def ask(client, question: str) -> list[dict]:
    import json
    r = client.post("/api/ask", json={"question": question}, auth=AUTH, headers=WRITE)
    assert r.status_code == 200
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
