export type Source = {
  n: number;
  chunkId: number;
  documentId: number;
  document: string;
  heading: string | null;
  page: number | null;
  text: string;
  match: ("keywords" | "meaning")[];
};

export type AskEvent =
  | { type: "sources"; sources: Source[] }
  | { type: "text"; text: string }
  | { type: "cite"; n: number; quote: string }
  | { type: "notice"; text: string }
  | { type: "error"; text: string }
  | { type: "done" };

export type Doc = {
  id: number;
  title: string;
  filename: string;
  kind: string;
  pages: number;
  passages: number;
  addedAt: string;
};

export type Status = { answers: "claude" | "offline"; search: "hybrid" | "keywords"; documents: number };

export type Passage = { id: number; heading: string | null; page: number | null; text: string };

// The server rejects writes without this header, so another site can't post here with the reader's login.
const WRITE = { "X-Requested-With": "margin" };

async function check(res: Response): Promise<Response> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `The server said ${res.status}`);
  }
  return res;
}

export const api = {
  status: async (): Promise<Status> => (await check(await fetch("/api/status"))).json(),
  documents: async (): Promise<Doc[]> => (await check(await fetch("/api/documents"))).json(),
  document: async (id: number): Promise<{ id: number; title: string; passages: Passage[] }> =>
    (await check(await fetch(`/api/documents/${id}`))).json(),

  upload: async (file: File): Promise<{ id: number; title: string; passages: number }> => {
    const form = new FormData();
    form.append("file", file);
    return (await check(await fetch("/api/documents", { method: "POST", headers: WRITE, body: form }))).json();
  },

  remove: async (id: number): Promise<void> => {
    await check(await fetch(`/api/documents/${id}`, { method: "DELETE", headers: WRITE }));
  },

  /** POSTs the question and calls onEvent for each server-sent event as it arrives. */
  ask: async (question: string, onEvent: (e: AskEvent) => void, signal: AbortSignal): Promise<void> => {
    const res = await check(
      await fetch("/api/ask", {
        method: "POST",
        headers: { ...WRITE, "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        signal,
      }),
    );
    const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = frame
          .split("\n")
          .filter((l) => l.startsWith("data: "))
          .map((l) => l.slice(6))
          .join("\n");
        if (data) onEvent(JSON.parse(data));
      }
    }
  },
};
