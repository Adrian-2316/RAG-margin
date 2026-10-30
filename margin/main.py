import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .answer import ClaudeAnswerer, OfflineAnswerer, sources_event
from .config import Settings, get_settings
from .db import make_engine, make_sessionmaker
from .embeddings import VoyageEmbedder
from .library import Library
from .parsing import UnsupportedFile
from .search import SearchIndex
from .security import SECURITY_HEADERS, Auth, basic, require_user

log = logging.getLogger("margin")
ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "dist"


def create_app(settings: Settings | None = None, answerer=None, embedder=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url, settings.embedding_dim)
        sessions = make_sessionmaker(engine)
        emb = embedder or (VoyageEmbedder(settings.voyage_api_key, settings.voyage_model, settings.embedding_dim)
                           if settings.voyage_api_key else None)
        index = SearchIndex(sessions, emb)
        app.state.library = Library(sessions, index)
        app.state.answerer = answerer or (
            ClaudeAnswerer(AsyncAnthropic(api_key=settings.anthropic_api_key), settings.margin_model, settings.margin_effort)
            if settings.anthropic_api_key else OfflineAnswerer())
        index.rebuild()
        if settings.seed_library:
            app.state.library.seed(ROOT / "seed_docs")
        log.info("Margin ready: answers=%s, search=%s", app.state.answerer.name,
                 "hybrid (" + emb.name + ")" if emb else "keywords")
        yield
        engine.dispose()

    app = FastAPI(title="Margin", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.auth = Auth(settings)
    app.state.settings = settings

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/status", dependencies=[Depends(require_user)])
    def status(request: Request):
        lib: Library = request.app.state.library
        return {"answers": request.app.state.answerer.name,
                "search": "hybrid" if lib.index.embedder else "keywords",
                "documents": len(lib.documents())}

    @app.get("/api/documents", dependencies=[Depends(require_user)])
    def documents(request: Request):
        return [{"id": d.id, "title": d.title, "filename": d.filename, "kind": d.kind, "pages": d.pages,
                 "passages": n, "addedAt": d.created_at.isoformat()} for d, n in request.app.state.library.documents()]

    @app.get("/api/documents/{document_id}", dependencies=[Depends(require_user)])
    def document(document_id: int, request: Request):
        found = request.app.state.library.passages(document_id)
        if not found:
            raise HTTPException(404, "No such document")
        doc, chunks = found
        return {"id": doc.id, "title": doc.title, "kind": doc.kind,
                "passages": [{"id": c.id, "heading": c.heading, "page": c.page, "text": c.text} for c in chunks]}

    @app.post("/api/documents", status_code=201, dependencies=[Depends(require_user)])
    async def upload(file: UploadFile, request: Request):
        limit = settings.max_upload_mb * 1024 * 1024
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"Files can be up to {settings.max_upload_mb} MB")
        try:
            doc = request.app.state.library.add(file.filename or "upload.txt", data)
        except UnsupportedFile as e:
            raise HTTPException(415, str(e)) from e
        return {"id": doc.id, "title": doc.title, "passages": len(doc.chunks)}

    @app.delete("/api/documents/{document_id}", status_code=204, dependencies=[Depends(require_user)])
    def delete(document_id: int, request: Request):
        if not request.app.state.library.remove(document_id):
            raise HTTPException(404, "No such document")

    class Question(BaseModel):
        question: str = Field(min_length=3, max_length=1000)

    @app.post("/api/ask", dependencies=[Depends(require_user)])
    async def ask(q: Question, request: Request):
        lib: Library = request.app.state.library
        hits = lib.index.search(q.question, settings.top_k)
        answerer = request.app.state.answerer

        async def events():
            yield _sse(sources_event(hits))
            if not hits:
                yield _sse({"type": "text", "text": "I couldn't find anything about that in the library. "
                                                    "Try other words, or add the document that covers it."})
            else:
                try:
                    async for event in answerer.stream(q.question, hits):
                        yield _sse(event)
                except Exception as e:  # report and end the stream cleanly; details stay in the log
                    log.exception("Answer failed")
                    yield _sse({"type": "error", "text": "Writing the answer failed. Try again in a moment."
                                if not isinstance(e, HTTPException) else e.detail})
            yield _sse({"type": "done"})

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if WEB.exists():
        app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str, _: str = Depends(require_user)):
            return FileResponse(WEB / "index.html")

    return app


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


app = create_app()
