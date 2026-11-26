"""Ship the Georgian demo documents' readings with the app, in demo_documents/ge/_readings/.

The dashboard looks there after its private cache (documents/_read_cache/), so the deployed demo shows the
demo documents instantly and never depends on Gemini on stage. On Cloud Run the private cache is empty after
every deploy and documents/ isn't uploaded; this folder is (the documents are simulated, so their readings
may be committed and deployed).

The readings are copied from an eval run, never read separately, so what ships is exactly what the eval
scored. Saved under a hash of each document's bytes (like the dashboard's cache): if
generate_demo_documents.py makes a document again, its old reading no longer matches and is removed here.

    python evals/run_paperwork_eval.py --source gemini --set ge        # read and score (about 18 Gemini calls)
    python -m paperwork.ship_readings --from evals/results/paperwork/<run>
    python evals/run_paperwork_eval.py --source shipped                 # score what ships, no Gemini calls
    python -m paperwork.ship_readings                                   # which demo documents have a reading
    python -m paperwork.ship_readings --embeddings     # also the passages' embeddings (questions, paperwork/rag.py)

Embeddings are not scored like readings: they are the same vectors whoever asks for them (evals/run_rag_eval.py
--embeddings scores the search that uses them). Already saved ones are copied from the private cache.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from paperwork.extract import PROMPT_VERSION

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo_documents" / "ge"
SHIPPED = DEMO_DIR / "_readings"
STEPS = ("classify", "extract")


def content_key(path):
    """The same key as CachedReader(by_content=True)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:24]


def demo_documents():
    """[(load, file path)] for every document named in a demo load's answer key."""
    found = []
    for load_dir in sorted(p for p in DEMO_DIR.iterdir() if p.is_dir() and (p / "expected.json").exists()):
        expected = json.loads((load_dir / "expected.json").read_text(encoding="utf-8"))
        found += [(load_dir.name, load_dir / name) for name in expected["documents"].values()]
    return found


def status():
    """Print which demo documents have a shipped reading; return how many are missing or old."""
    missing = 0
    for load, path in demo_documents():
        states = []
        for step in STEPS:
            saved = SHIPPED / f"{content_key(path)}.{step}.json"
            if not saved.exists():
                states.append(f"{step} MISSING")
                missing += 1
                continue
            version = json.loads(saved.read_text(encoding="utf-8"))["meta"].get("prompt_version")
            if step == "extract" and version != PROMPT_VERSION:
                states.append(f"{step} OLD PROMPT ({version})")
                missing += 1
            else:
                states.append(f"{step} ok")
        print(f"  {load}/{path.name:<8} " + ", ".join(states))
    return missing


def ship(run_dir, allow_old=False):
    """Copy an eval run's readings of the demo documents into SHIPPED; remove readings of old documents."""
    SHIPPED.mkdir(parents=True, exist_ok=True)
    wanted, skipped = set(), 0
    for load, path in demo_documents():
        for step in STEPS:
            source = run_dir / load / f"{path.name}.{step}.json"
            target = SHIPPED / f"{content_key(path)}.{step}.json"
            if not source.exists():
                print(f"  skip {load}/{path.name} {step}: not in {run_dir.name} (Gemini didn't answer? run --resume)")
                skipped += 1
                continue
            version = json.loads(source.read_text(encoding="utf-8"))["meta"].get("prompt_version")
            if step == "extract" and version != PROMPT_VERSION and not allow_old:
                print(f"  skip {load}/{path.name} {step}: read with prompt {version}, current is {PROMPT_VERSION}")
                skipped += 1
                continue
            shutil.copyfile(source, target)
            wanted.add(target.name)
    current = {content_key(p) for _, p in demo_documents()}
    for old in SHIPPED.glob("*.json"):
        if old.name.startswith("emb-"):
            continue   # embeddings: ship_embeddings() keeps them in step
        if old.name not in wanted and old.name.split(".")[0] not in current:
            old.unlink()
            print(f"  removed {old.name} (no demo document has this content any more)")
    return skipped


def _demo_passage_texts():
    from paperwork.rag import document_pages, passages
    return [p["text"] for _, path in demo_documents() for p in passages(path.name, document_pages(path))]


def ship_embeddings():
    """Every demo passage's embedding in SHIPPED: copied from the private cache if saved there, else asked
    from Gemini (one request per 100 passages). Embeddings of passages that no longer exist are removed."""
    from paperwork.rag import SavedGeminiEmbeddings
    private = ROOT / "documents" / "_read_cache"
    shipped = SavedGeminiEmbeddings(SHIPPED)
    texts = _demo_passage_texts()
    wanted = set()
    for text in texts:
        target = shipped._file(SHIPPED, text, "RETRIEVAL_DOCUMENT")
        wanted.add(target.name)
        saved = shipped._file(private, text, "RETRIEVAL_DOCUMENT")
        if not target.exists() and saved.exists():
            shutil.copyfile(saved, target)
    shipped.embed_documents(texts)   # only the ones still missing are sent
    removed = [old for old in SHIPPED.glob("emb-*.json") if old.name not in wanted]
    for old in removed:
        old.unlink()
    print(f"  embeddings: {len(wanted)} passages, {shipped.calls} Gemini request(s), {len(removed)} old removed")


def embeddings_missing():
    from paperwork.rag import SavedGeminiEmbeddings
    probe = SavedGeminiEmbeddings(SHIPPED)
    return sum(not probe._file(SHIPPED, t, "RETRIEVAL_DOCUMENT").exists() for t in _demo_passage_texts())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="run_dir", type=Path, help="an eval run folder (--source gemini --set ge)")
    parser.add_argument("--allow-old", action="store_true", help="also ship extractions from an older prompt")
    parser.add_argument("--embeddings", action="store_true", help="also ship the demo passages' embeddings")
    args = parser.parse_args()
    if args.run_dir:
        if not args.run_dir.is_dir():
            sys.exit(f"Not a folder: {args.run_dir}")
        skipped = ship(args.run_dir, args.allow_old)
        print(f"Shipped from {args.run_dir.name}" + (f" ({skipped} skipped)" if skipped else ""))
    if args.embeddings:
        ship_embeddings()
    print(f"Readings in {SHIPPED.relative_to(ROOT)} (prompt {PROMPT_VERSION}):")
    missing = status()
    no_embedding = embeddings_missing()
    print(f"  embeddings: " + (f"{no_embedding} passage(s) without one (--embeddings)" if no_embedding else "all passages"))
    missing += no_embedding
    print("All demo documents have a shipped reading" if not missing else f"{missing} reading(s) missing or old")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
