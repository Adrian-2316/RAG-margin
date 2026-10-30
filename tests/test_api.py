from fastapi.testclient import TestClient

from margin.main import create_app
from tests.conftest import AUTH, WRITE, FakeEmbedder, ask, make_pdf, settings


def test_health_is_open_and_everything_else_needs_the_login(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents", auth=("reader", "wrong")).status_code == 401
    assert client.get("/api/documents", auth=AUTH).status_code == 200


def test_writes_without_the_csrf_header_are_refused(client):
    r = client.post("/api/ask", json={"question": "holiday days?"}, auth=AUTH)
    assert r.status_code == 403
    assert client.delete("/api/documents/1", auth=AUTH).status_code == 403


def test_security_headers_are_set(client):
    h = client.get("/api/health").headers
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"


def test_the_sample_library_is_loaded(client):
    docs = client.get("/api/documents", auth=AUTH).json()
    assert {d["title"] for d in docs} >= {"People Handbook", "Barista Handbook", "Wholesale Terms"}
    assert all(d["passages"] > 0 for d in docs)


def test_upload_read_and_remove_a_pdf(client):
    pdf = make_pdf(["Returns policy", "Customers can return beans within 14 days."])
    r = client.post("/api/documents", files={"file": ("returns.pdf", pdf, "application/pdf")}, auth=AUTH, headers=WRITE)
    assert r.status_code == 201
    doc_id = r.json()["id"]
    passages = client.get(f"/api/documents/{doc_id}", auth=AUTH).json()["passages"]
    assert passages[0]["page"] == 1

    events = ask(client, "Within how many days can customers return beans?")
    sources = events[0]["sources"]
    assert sources[0]["documentId"] == doc_id

    assert client.delete(f"/api/documents/{doc_id}", auth=AUTH, headers=WRITE).status_code == 204
    assert client.get(f"/api/documents/{doc_id}", auth=AUTH).status_code == 404


def test_upload_limits(tmp_path):
    with TestClient(create_app(settings(tmp_path, max_upload_mb=1, seed_library=False))) as c:
        big = b"a" * (1024 * 1024 + 10)
        r = c.post("/api/documents", files={"file": ("big.txt", big)}, auth=AUTH, headers=WRITE)
        assert r.status_code == 413
        r = c.post("/api/documents", files={"file": ("run.sh", b"rm -rf /")}, auth=AUTH, headers=WRITE)
        assert r.status_code == 415


def test_offline_answer_quotes_and_cites_the_right_passage(client):
    events = ask(client, "How many holiday days do I get?")
    assert [e["type"] for e in events][0] == "sources" and events[-1]["type"] == "done"
    sources = {s["n"]: s for s in events[0]["sources"]}
    cites = [e for e in events if e["type"] == "cite"]
    assert cites, events
    first = sources[cites[0]["n"]]
    assert first["document"] == "People Handbook"
    assert cites[0]["quote"] in first["text"]
    assert "25 days" in cites[0]["quote"]


def test_offline_answer_admits_when_nothing_matches(client):
    events = ask(client, "Who won the world cup?")
    text = "".join(e.get("text", "") for e in events if e["type"] == "text")
    assert "couldn't find" in text
    assert not [e for e in events if e["type"] == "cite"]


def test_question_length_is_bounded(client):
    r = client.post("/api/ask", json={"question": "x" * 5000}, auth=AUTH, headers=WRITE)
    assert r.status_code == 422


def test_hybrid_search_finds_passages_by_meaning(tmp_path):
    with TestClient(create_app(settings(tmp_path), embedder=FakeEmbedder())) as c:
        assert c.get("/api/status", auth=AUTH).json()["search"] == "hybrid"
        # "vacation" never appears in the documents; only the embedding links it to "holiday".
        sources = ask(c, "vacation allowance")[0]["sources"]
        top = sources[0]
        assert top["heading"] == "People Handbook › Holidays"
        assert "meaning" in top["match"]
