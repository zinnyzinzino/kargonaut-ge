"""Ask the documents (RAG): answer a dispatcher's question about one load's documents, with the passages
the answer comes from.

    START -> retrieve -> (any passages?) -> answer -> verify -> END
                                \\-> no: END

Same design rule as the rest of Kargonaut: Python does everything it can, Gemini only words the answer,
and Python checks that answer before the dispatcher sees it.
- Text: taken from the PDFs by Python (pypdf, their text layer), no Gemini. Photos and scans have no text
  layer and are not searched (yet).
- Passages: the text cut into clauses (a numbered term, a labelled field), each with its document and page.
- retrieve: two searches, merged (reciprocal rank fusion):
  keywords (BM25, pure Python, always works) and meaning (Gemini embeddings in LangChain's
  InMemoryVectorStore; finds "waiting time" for "detention" and English text for a Georgian question).
  If embeddings are unavailable (quota), keywords alone.
- answer: Gemini answers ONLY from the retrieved passages and copies the exact words it used (quotes).
- verify: every quote must really be in its passage, and every number in the answer must be in a quoted
  passage (number_check.py, the same check as the dispatcher's answers). If not, the answer is withheld
  and the dispatcher sees the passages only. "The documents don't say" is an allowed answer.

Embeddings are saved by text (like the readings), so a passage is embedded once; the demo documents'
embeddings ship with the app in demo_documents/ge/_readings/ (paperwork/ship_readings.py).
"""
import hashlib
import json
import math
import os
import re
import threading
import unicodedata
from collections import Counter
from pathlib import Path
from typing import TypedDict

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langgraph.graph import END, START, StateGraph

from number_check import _numbers
from paperwork.extract import GeminiReader, ReadingFailed, _check_allowed

EMBEDDING_MODEL = os.getenv("KARGONAUT_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIMENSIONS = 768
PASSAGE_TARGET_CHARS = 500     # passages grow line by line up to about this size...
PASSAGE_MAX_CHARS = 900        # ...and are cut at a sentence end above this
TOP_K = 4                      # passages given to Gemini
LANGUAGE_NAMES = {"ka": "Georgian", "en": "English"}


# ---------------------------------------------------------------- text and passages (Python only)

def document_pages(path):
    """[(page number, text)] from a PDF's text layer; [] for a photo or a PDF without text."""
    _check_allowed(path)   # passages are sent to Gemini: never from documents/originals/
    if Path(path).suffix.lower() != ".pdf":
        return []
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
        return [(i, page.extract_text() or "") for i, page in enumerate(reader.pages, 1)]
    except Exception:   # a damaged PDF: nothing to search, the reading and checks still work
        return []


# A new passage starts at a numbered term ("4. Detention", "5) ...") or a heading line ("REQUIREMENTS:")
_NEW_CLAUSE = re.compile(r"^\s*(\d{1,2}[.)]\s|[A-Z][A-Z /&-]{3,40}:)")


def _clean(text):
    """NFKC (the PDF ligature "ﬁ" -> "fi"), one space between words."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _split_long(text):
    if len(text) <= PASSAGE_MAX_CHARS:
        return [text]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        if current and len(current) + len(sentence) > PASSAGE_TARGET_CHARS:
            parts.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    # a "sentence" longer than the maximum (no full stops): cut by length
    return [p[i:i + PASSAGE_MAX_CHARS] for p in parts for i in range(0, len(p), PASSAGE_MAX_CHARS)]


def passages(name, pages):
    """The document's text cut into passages: [{"id", "document", "page", "text"}]."""
    found = []
    for page, text in pages:
        current = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            size = sum(len(x) for x in current)
            if current and (_NEW_CLAUSE.match(line) or size + len(line) > PASSAGE_TARGET_CHARS):
                found.append((page, " ".join(current)))
                current = []
            current.append(line)
        if current:
            found.append((page, " ".join(current)))
    # A short piece that isn't a clause of its own (a value cut off from its label: "30 days from invoice"
    # after "Payment terms") goes back onto the passage before it
    merged = []
    for page, text in found:
        if merged and merged[-1][0] == page and len(text) < 80 and not _NEW_CLAUSE.match(text)                 and len(merged[-1][1]) + len(text) <= PASSAGE_MAX_CHARS:
            merged[-1] = (page, f"{merged[-1][1]} {text}")
        else:
            merged.append((page, text))
    result = []
    for page, text in merged:
        for part in _split_long(_clean(text)):
            if len(part) >= 15:   # a lone page number or label says nothing
                result.append({"id": f"{name}#{len(result) + 1}", "document": name, "page": page, "text": part})
    return result


# ---------------------------------------------------------------- keyword search (BM25, Python only)

# Question words that say nothing about the topic ("is" matched "the carrier IS paid" over "Detention")
STOP_WORDS = set("""a an the is are was be been do does did we our us you your it its this that these those
what which who whom when where why how much many any there here of to for in on at by with from and or if
can could should would will shall may must about than then so not no
რა რომ რომელი რომელიც როდის როგორ სად ვინ რამდენი რამდენს რამდენია არის იყო და ან თუ ეს ის ამ იმ ჩვენ ჩვენი
მე შენ თქვენ უნდა აქვს აქვთ არ ვერ კი ხომ რის რისი""".split())


def _tokens(text):
    """Lower-case topic words; long words cut to 6 letters, a rough stem that also works for Georgian
    endings (ლოდინი / ლოდინის / ლოდინისთვის -> ლოდინი)."""
    words = re.findall(r"\w+", unicodedata.normalize("NFKC", text).lower())
    return [w[:6] for w in words if len(w) > 1 and w not in STOP_WORDS]


def keyword_ranking(question, items, k1=1.5, b=0.75):
    """BM25: [(score, index)] best first, only passages sharing a word with the question."""
    docs = [_tokens(p["text"]) for p in items]
    if not docs:
        return []
    average = sum(len(d) for d in docs) / len(docs)
    frequency = Counter(t for d in docs for t in set(d))
    scores = []
    for i, doc in enumerate(docs):
        counts, score = Counter(doc), 0.0
        for term in set(_tokens(question)):
            if counts[term]:
                idf = math.log(1 + (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                score += idf * counts[term] * (k1 + 1) / (counts[term] + k1 * (1 - b + b * len(doc) / average))
        if score > 0:
            scores.append((score, i))
    return sorted(scores, reverse=True)


# ---------------------------------------------------------------- meaning search (Gemini embeddings)

class SavedGeminiEmbeddings(Embeddings):
    """LangChain embeddings backed by Gemini, saved by text in `folder` (read-only `also_from`), so a
    passage is embedded once. calls: how many embedding requests were actually sent."""

    def __init__(self, folder, also_from=(), model=EMBEDDING_MODEL, client=None):
        self.folder, self.also_from, self.model = Path(folder), [Path(f) for f in also_from], model
        self.folder.mkdir(parents=True, exist_ok=True)
        self._client, self.calls = client, 0

    @property
    def client(self):
        if self._client is None:
            from google import genai
            from google.genai import types
            self._client = genai.Client(http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1), timeout=60_000))
        return self._client

    def _file(self, folder, text, task):
        key = hashlib.sha256(f"{self.model}|{EMBEDDING_DIMENSIONS}|{task}|{text}".encode()).hexdigest()[:24]
        return folder / f"emb-{key}.json"

    def _embed(self, texts, task):
        vectors, missing = {}, []
        for i, text in enumerate(texts):
            for folder in [self.folder, *self.also_from]:
                saved = self._file(folder, text, task)
                if saved.exists():
                    vectors[i] = json.loads(saved.read_text(encoding="utf-8"))
                    break
            else:
                missing.append(i)
        if missing:
            from google.genai import errors, types
            config = types.EmbedContentConfig(task_type=task, output_dimensionality=EMBEDDING_DIMENSIONS)
            for start in range(0, len(missing), 100):     # at most 100 texts per request
                batch = missing[start:start + 100]
                self.calls += 1
                try:
                    response = self.client.models.embed_content(model=self.model, contents=[texts[i] for i in batch],
                                                                config=config)
                except errors.APIError as exc:
                    raise ReadingFailed(f"{self.model}: {exc.code} {exc.status or ''}".strip()) from exc
                except Exception as exc:
                    raise ReadingFailed(f"{self.model}: {type(exc).__name__}") from exc
                for i, embedding in zip(batch, response.embeddings):
                    vectors[i] = [round(v, 6) for v in embedding.values]
                    saved = self._file(self.folder, texts[i], task)
                    temporary = saved.with_name(f"{saved.name}.{os.getpid()}.{threading.get_ident()}.tmp")
                    try:
                        temporary.write_text(json.dumps(vectors[i]), encoding="utf-8")
                        os.replace(temporary, saved)
                    except OSError:
                        temporary.unlink(missing_ok=True)
        return [vectors[i] for i in range(len(texts))]

    def embed_documents(self, texts):
        return self._embed(list(texts), "RETRIEVAL_DOCUMENT")

    def embed_query(self, text):
        return self._embed([text], "RETRIEVAL_QUERY")[0]


def meaning_ranking(question, items, embeddings):
    """[(score, index)] best first, from LangChain's in-memory vector store (cosine similarity)."""
    store = InMemoryVectorStore(embedding=embeddings)
    store.add_documents([Document(page_content=p["text"], metadata={"i": i}) for i, p in enumerate(items)],
                        ids=[p["id"] for p in items])
    hits = store.similarity_search_with_score(question, k=min(len(items), 10))
    return [(score, doc.metadata["i"]) for doc, score in hits]


def fuse(*rankings, k=60):
    """Reciprocal rank fusion: a passage high in either list comes first. [(score, index)]"""
    scores = Counter()
    for ranking in rankings:
        for rank, (_, i) in enumerate(ranking):
            scores[i] += 1 / (k + rank + 1)
    return sorted(((s, i) for i, s in scores.items()), reverse=True)


# ---------------------------------------------------------------- the graph

ANSWER_PROMPT = """You answer a truck dispatcher's question about the documents of one load (rate confirmation,
bill of lading, delivery order, proof of delivery), using ONLY the numbered passages below. They are text
copied from the documents.

Rules:
- Answer in {language}, in one to three short sentences. Keep company names, truck types, amounts and
  document numbers exactly as written.
- Every fact must come from the passages: no outside knowledge, no guessing, no new calculations.
- quotes: for each passage you used, its number and the exact words you relied on, copied character for
  character from that passage (a short span, untranslated, without "..." inside).
- If the passages don't answer the question, set found to false, say in one sentence that the documents
  don't say it, and give no quotes.

Question: {question}

Passages:
{passages}
"""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "answer": {"type": "string"},
        "quotes": {"type": "array", "items": {
            "type": "object",
            "properties": {"passage": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["passage", "text"]}},
    },
    "required": ["found", "answer", "quotes"],
}


class AskState(TypedDict, total=False):
    question: str
    lang: str
    passages: list        # every passage of the load's documents
    hits: list            # the retrieved passages, best first (each with "n", its number in the prompt)
    retrieval: str        # "keywords+meaning" or "keywords" (embeddings unavailable)
    found: bool
    answer: str
    quotes: list          # [{"passage": n, "text": ...}] checked
    status: str           # answered | not_found | unverified | no_answer | no_passages | no_text
    problems: list        # why an answer was withheld (verify)
    calls: list


def _config(config, key):
    return (config or {}).get("configurable", {}).get(key)


def retrieve(state, config=None):
    items = state.get("passages") or []
    if not items:
        return {"hits": [], "status": "no_text", "retrieval": "none"}
    keywords = keyword_ranking(state["question"], items)
    embeddings, rankings, retrieval = _config(config, "embeddings"), [keywords], "keywords"
    if embeddings is not None:
        try:
            rankings.append(meaning_ranking(state["question"], items, embeddings))
            retrieval = "keywords+meaning"
        except ReadingFailed:
            pass   # quota or network: keywords alone still find passages that share words with the question
    ranked = fuse(*rankings)[:TOP_K]
    hits = [{**items[i], "n": n} for n, (_, i) in enumerate(ranked, 1)]
    return {"hits": hits, "retrieval": retrieval, "status": "retrieved" if hits else "no_passages"}


def _any_hits(state):
    return "answer" if state.get("hits") else END


def answer(state, config=None):
    reader = _config(config, "reader") or GeminiReader()
    listed = "\n".join(f"[{h['n']}] ({h['document']}, page {h['page']}) {h['text']}" for h in state["hits"])
    prompt = ANSWER_PROMPT.format(language=LANGUAGE_NAMES.get(state.get("lang"), "English"),
                                  question=state["question"], passages=listed)
    try:
        reply, meta = reader.generate([prompt], ANSWER_SCHEMA, label="question")
    except ReadingFailed as exc:
        return {"status": "no_answer", "problems": [str(exc)]}
    return {"found": bool(reply.get("found")), "answer": (reply.get("answer") or "").strip(),
            "quotes": reply.get("quotes") or [], "calls": [{"step": "answer", **meta}]}


def _normal(text):
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[\"'“”„«»‘’`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _unquoted_numbers(answer, texts):
    """Numbers in the answer that no quoted passage contains. Stricter than number_check.py (the dispatcher's
    check ignores 1-10, dates and clock times): here "the first 5 hours are free" against "the first 2 hours"
    must fail, and so must a time or a percentage that isn't in the passage (review, 25 Nov). A date or time
    in the passage also counts by its parts (30.11.2026 -> 30, 11, 2026), so the answer may write it differently."""
    known = set()
    for text in texts:
        known.update(_numbers(text))
        known.update(float(n) for n in re.findall(r"\d+", text))
    return [int(n) if n == int(n) else n for n in _numbers(answer) if not any(abs(n - k) < 1e-9 for k in known)]


def verify(state):
    """Python checks Gemini's answer: quotes really in the passages, numbers really in the quoted passages."""
    if state.get("status") == "no_answer":
        return {}
    if not state.get("found"):
        return {"status": "not_found", "quotes": []}
    hits, problems, quoted = {h["n"]: h for h in state["hits"]}, [], []
    for quote in state.get("quotes", []):
        passage = hits.get(quote.get("passage"))
        text = _normal(quote.get("text", ""))
        if passage is None:
            problems.append(f"quote from passage {quote.get('passage')}, which wasn't given")
        elif len(text) < 3 or text not in _normal(passage["text"]):
            problems.append(f"quote not in passage {passage['n']}: {quote.get('text')!r}")
        else:
            quoted.append(passage)
    if not quoted:
        problems.append("no quote backs the answer")
    unsourced = _unquoted_numbers(state.get("answer", ""), [p["text"] for p in quoted])
    if unsourced:
        problems.append(f"numbers not in the quoted passages: {unsourced}")
    if problems:
        return {"status": "unverified", "problems": problems}
    return {"status": "answered", "quotes": [{**q, "document": hits[q["passage"]]["document"],
                                              "page": hits[q["passage"]]["page"]} for q in state["quotes"]]}


def build_graph():
    graph = StateGraph(AskState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("answer", answer)
    graph.add_node("verify", verify)
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", _any_hits, ["answer", END])
    graph.add_edge("answer", "verify")
    graph.add_edge("verify", END)
    return graph.compile()


def ask(question, items, lang="en", reader=None, embeddings=None):
    """Answer a question about one load's passages. Returns the final AskState; only status "answered"
    shows Gemini's answer, every other status shows the passages (hits) only."""
    config = {"configurable": {"reader": reader, "embeddings": embeddings}}
    return build_graph().invoke({"question": question, "lang": lang, "passages": items, "calls": []}, config=config)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("python -m paperwork.rag \"question\" file.pdf [file.pdf ...]")
        sys.exit(1)
    found = [p for f in sys.argv[2:] for p in passages(Path(f).name, document_pages(f))]
    result = ask(sys.argv[1], found, embeddings=SavedGeminiEmbeddings(Path("documents") / "_read_cache"))
    print(f"{len(found)} passages, retrieval: {result.get('retrieval')}, status: {result.get('status')}")
    for h in result.get("hits", []):
        print(f"  [{h['n']}] {h['document']} p{h['page']}: {h['text'][:160]}")
    if result.get("status") == "answered":
        print(f"\n{result['answer']}")
    for problem in result.get("problems", []):
        print(f"  withheld: {problem}")
