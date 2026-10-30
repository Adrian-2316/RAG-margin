import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type AskEvent, type Doc, type Passage, type Source, type Status } from "./api";

type Part = { t: "text"; text: string } | { t: "cite"; n: number };

type Turn = {
  id: number;
  question: string;
  sources: Source[];
  parts: Part[];
  quotes: Record<number, string[]>;
  notice?: string;
  error?: string;
  done: boolean;
};

const SUGGESTIONS = [
  "How many holiday days do I get, and can I carry them over?",
  "What temperature should oat milk be steamed to?",
  "When does a wholesale customer get free delivery?",
  "How often do the grinder burrs get replaced?",
];

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [reading, setReading] = useState<{ documentId: number; chunkId?: number; quotes?: string[] } | null>(null);
  const busy = turns.some((t) => !t.done);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const closeReader = useCallback(() => setReading(null), []);

  const refresh = () => {
    api.status().then(setStatus).catch(() => setStatus(null));
    api.documents().then(setDocs).catch(() => setDocs([]));
  };
  useEffect(refresh, []);

  const update = (id: number, change: (t: Turn) => Turn) =>
    setTurns((all) => all.map((t) => (t.id === id ? change(t) : t)));

  const ask = async (question: string) => {
    const id = Date.now();
    setTurns((all) => [...all, { id, question, sources: [], parts: [], quotes: {}, done: false }]);
    requestAnimationFrame(() => bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }));
    abort.current = new AbortController();
    const onEvent = (e: AskEvent) =>
      update(id, (t) => {
        switch (e.type) {
          case "sources":
            return { ...t, sources: e.sources };
          case "text": {
            const last = t.parts[t.parts.length - 1];
            return last?.t === "text"
              ? { ...t, parts: [...t.parts.slice(0, -1), { t: "text", text: last.text + e.text }] }
              : { ...t, parts: [...t.parts, { t: "text", text: e.text }] };
          }
          case "cite": {
            const last = t.parts[t.parts.length - 1];
            const parts: Part[] = last?.t === "cite" && last.n === e.n ? t.parts : [...t.parts, { t: "cite", n: e.n }];
            return { ...t, parts, quotes: { ...t.quotes, [e.n]: [...(t.quotes[e.n] ?? []), e.quote] } };
          }
          case "notice":
            return { ...t, notice: e.text };
          case "error":
            return { ...t, error: e.text };
          case "done":
            return { ...t, done: true };
        }
      });
    try {
      await api.ask(question, onEvent, abort.current.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") update(id, (t) => ({ ...t, error: (err as Error).message }));
    } finally {
      update(id, (t) => ({ ...t, done: true }));
    }
  };

  return (
    <div className="app">
      <Library docs={docs} onChange={refresh} onOpen={(documentId) => setReading({ documentId })} />

      <main className="desk">
        <header className="top">
          <div className="brand">
            <span className="mark" aria-hidden="true" />
            <span>Margin</span>
          </div>
          {status && (
            <div className="modes">
              <span className={`mode ${status.answers === "claude" ? "on" : ""}`}>
                {status.answers === "claude" ? "Answers by Claude" : "Offline answers"}
              </span>
              <span className={`mode ${status.search === "hybrid" ? "on" : ""}`}>
                {status.search === "hybrid" ? "Keywords + meaning" : "Keyword search"}
              </span>
            </div>
          )}
        </header>

        {turns.length === 0 ? (
          <section className="welcome">
            <h1>Ask the handbook anything.</h1>
            <p>
              Margin reads your documents and answers in plain words. Every sentence points to the passage it came from,
              so you can check it yourself.
            </p>
            <AskBox busy={busy} onAsk={ask} autoFocus />
            <div className="ideas">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="idea" onClick={() => ask(s)} disabled={busy}>
                  {s}
                </button>
              ))}
            </div>
          </section>
        ) : (
          <>
            <div className="turns">
              {turns.map((t) => (
                <TurnView key={t.id} turn={t} onRead={(s, quotes) => setReading({ documentId: s.documentId, chunkId: s.chunkId, quotes })} />
              ))}
              <div ref={bottom} />
            </div>
            <div className="dock">
              <AskBox busy={busy} onAsk={ask} onStop={() => abort.current?.abort()} />
            </div>
          </>
        )}
      </main>

      {reading && <Reader {...reading} onClose={closeReader} />}
    </div>
  );
}

function AskBox({ busy, onAsk, onStop, autoFocus }: { busy: boolean; onAsk: (q: string) => void; onStop?: () => void; autoFocus?: boolean }) {
  const [q, setQ] = useState("");
  const submit = () => {
    const question = q.trim();
    if (question.length < 3 || busy) return;
    setQ("");
    onAsk(question);
  };
  return (
    <form className="ask" onSubmit={(e) => (e.preventDefault(), submit())}>
      <textarea
        value={q}
        rows={1}
        maxLength={500}
        autoFocus={autoFocus}
        placeholder="Ask a question about your documents…"
        aria-label="Your question"
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      {busy && onStop ? (
        <button type="button" className="go stop" onClick={onStop}>
          Stop
        </button>
      ) : (
        <button className="go" disabled={busy || q.trim().length < 3}>
          Ask
        </button>
      )}
    </form>
  );
}

function TurnView({ turn, onRead }: { turn: Turn; onRead: (s: Source, quotes: string[]) => void }) {
  const [active, setActive] = useState<number | null>(null);
  const cited = new Set(turn.parts.flatMap((p) => (p.t === "cite" ? [p.n] : [])));
  // Show cited sources first, then the rest of what the search found, quieter.
  const shown = [...turn.sources].sort((a, b) => Number(cited.has(b.n)) - Number(cited.has(a.n)) || a.n - b.n);
  const writing = !turn.done && turn.parts.length === 0;

  const focus = (n: number) => {
    setActive(n);
    document.getElementById(`src-${turn.id}-${n}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  return (
    <article className="turn">
      <h2 className="q">{turn.question}</h2>
      <div className="split">
        <div className="answer">
          {turn.notice && <p className="notice">{turn.notice}</p>}
          {writing && (
            <p className="thinking">
              <span className="dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              {turn.sources.length ? `Reading ${turn.sources.length} passages…` : "Searching the library…"}
            </p>
          )}
          <div className={`prose ${turn.done ? "" : "live"}`}>
            {turn.parts.map((p, i) =>
              p.t === "text" ? (
                <Inline key={i} text={p.text} />
              ) : (
                <button
                  key={i}
                  className={`cite ${active === p.n ? "on" : ""}`}
                  onMouseEnter={() => setActive(p.n)}
                  onFocus={() => setActive(p.n)}
                  onClick={() => focus(p.n)}
                  aria-label={`Source ${p.n}`}
                >
                  {p.n}
                </button>
              ),
            )}
          </div>
          {turn.error && <p className="error">{turn.error}</p>}
        </div>

        {turn.sources.length > 0 && (
          <aside className="margin" aria-label="Sources">
            {shown.map((s) => (
              <SourceCard
                key={s.n}
                id={`src-${turn.id}-${s.n}`}
                source={s}
                quotes={turn.quotes[s.n] ?? []}
                cited={cited.has(s.n)}
                quiet={turn.done && !cited.has(s.n)}
                active={active === s.n}
                onHover={() => setActive(s.n)}
                onRead={() => onRead(s, turn.quotes[s.n] ?? [])}
              />
            ))}
          </aside>
        )}
      </div>
    </article>
  );
}

function SourceCard(props: {
  id: string;
  source: Source;
  quotes: string[];
  cited: boolean;
  quiet: boolean;
  active: boolean;
  onHover: () => void;
  onRead: () => void;
}) {
  const { source: s, quotes } = props;
  const [open, setOpen] = useState(false);
  const section = s.heading?.split(" › ").slice(1).join(" › ");
  return (
    <div
      id={props.id}
      className={`src ${props.active ? "on" : ""} ${props.quiet ? "quiet" : ""}`}
      onMouseEnter={props.onHover}
    >
      <div className="src-head">
        <span className="num">{s.n}</span>
        <span className="where">
          <b>{s.document}</b>
          {section && <span> · {section}</span>}
          {s.page != null && <span> · p. {s.page}</span>}
        </span>
      </div>
      <p className={`src-text ${open || props.cited ? "open" : ""}`}>
        <Highlighted text={s.text} quotes={quotes} />
      </p>
      <div className="src-foot">
        <span className="tags">
          {s.match.map((m) => (
            <span key={m} className="tag">
              {m === "meaning" ? "similar meaning" : "keyword match"}
            </span>
          ))}
        </span>
        <span>
          {!props.cited && (
            <button className="link" onClick={() => setOpen(!open)}>
              {open ? "Less" : "More"}
            </button>
          )}
          <button className="link" onClick={props.onRead}>
            In context
          </button>
        </span>
      </div>
    </div>
  );
}

/** Wraps each quoted span of text in <mark>. */
function Highlighted({ text, quotes }: { text: string; quotes: string[] }) {
  const ranges: [number, number][] = [];
  for (const q of quotes) {
    const at = text.indexOf(q.trim());
    if (at >= 0) ranges.push([at, at + q.trim().length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const out: ReactNode[] = [];
  let pos = 0;
  for (const [start, end] of ranges) {
    if (start < pos) continue;
    out.push(text.slice(pos, start), <mark key={start}>{text.slice(start, end)}</mark>);
    pos = end;
  }
  out.push(text.slice(pos));
  return <>{out}</>;
}

/** Minimal inline formatting for answers: **bold** and line breaks. Everything else stays plain text. */
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*)/g).map((piece, i) =>
        piece.startsWith("**") && piece.endsWith("**") && piece.length > 4 ? <strong key={i}>{piece.slice(2, -2)}</strong> : piece,
      )}
    </>
  );
}

function Library({ docs, onChange, onOpen }: { docs: Doc[]; onChange: () => void; onOpen: (id: number) => void }) {
  const [note, setNote] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const passages = docs.reduce((n, d) => n + d.passages, 0);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    setNote(null);
    for (const file of Array.from(files)) {
      try {
        const doc = await api.upload(file);
        setNote({ kind: "ok", text: `Added “${doc.title}” in ${doc.passages} passages.` });
      } catch (err) {
        setNote({ kind: "bad", text: `${file.name}: ${(err as Error).message}` });
      }
    }
    setUploading(false);
    if (input.current) input.current.value = "";
    onChange();
  };

  const remove = async (d: Doc) => {
    if (!confirm(`Remove “${d.title}” from the library?`)) return;
    try {
      await api.remove(d.id);
    } catch (err) {
      setNote({ kind: "bad", text: (err as Error).message });
    }
    onChange();
  };

  return (
    <nav
      className={`library ${dragging ? "drop" : ""}`}
      onDragOver={(e) => (e.preventDefault(), setDragging(true))}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => (e.preventDefault(), setDragging(false), upload(e.dataTransfer.files))}
    >
      <div className="lib-head">
        <h3>Library</h3>
        <span className="count">
          {docs.length} documents · {passages} passages
        </span>
      </div>
      <ul className="docs">
        {docs.map((d) => (
          <li key={d.id}>
            <button className="doc" onClick={() => onOpen(d.id)} title={d.filename}>
              <span className={`kind k-${d.kind}`}>{d.kind}</span>
              <span className="doc-title">{d.title}</span>
              <span className="doc-meta">{d.passages}</span>
            </button>
            <button className="x" onClick={() => remove(d)} aria-label={`Remove ${d.title}`}>
              ×
            </button>
          </li>
        ))}
      </ul>
      <label className={`add ${uploading ? "busy" : ""}`}>
        <input ref={input} type="file" accept=".pdf,.md,.markdown,.txt" multiple onChange={(e) => upload(e.target.files)} disabled={uploading} />
        {uploading ? "Reading…" : "+ Add a document"}
        <small>PDF, Markdown or text · or drop it here</small>
      </label>
      {note && <p className={`lib-note ${note.kind}`}>{note.text}</p>}
    </nav>
  );
}

function Reader({ documentId, chunkId, quotes, onClose }: { documentId: number; chunkId?: number; quotes?: string[]; onClose: () => void }) {
  const [doc, setDoc] = useState<{ title: string; passages: Passage[] } | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.document(documentId).then(setDoc).catch(() => setFailed(true));
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [documentId, onClose]);

  useEffect(() => {
    if (doc && chunkId) document.getElementById(`p-${chunkId}`)?.scrollIntoView({ block: "center" });
  }, [doc, chunkId]);

  let lastHeading: string | null = null;
  return (
    <div className="veil" onClick={onClose}>
      <div className="reader" role="dialog" aria-modal="true" aria-label={doc?.title ?? "Document"} onClick={(e) => e.stopPropagation()}>
        <div className="reader-head">
          <h2>{doc?.title ?? (failed ? "Couldn't open this document" : "Opening…")}</h2>
          <button className="x big" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="reader-body">
          {doc?.passages.map((p) => {
            const section = p.heading?.split(" › ").slice(1).join(" › ") || null;
            const showHeading = section && section !== lastHeading;
            lastHeading = section;
            return (
              <div key={p.id}>
                {showHeading && <h4>{section}</h4>}
                {p.page != null && !section && <h4>Page {p.page}</h4>}
                <p id={`p-${p.id}`} className={p.id === chunkId ? "here" : ""}>
                  <Highlighted text={p.text} quotes={p.id === chunkId ? quotes ?? [] : []} />
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
