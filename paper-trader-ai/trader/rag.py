"""Retrieval-augmented generation store: chunking, embedding, and metadata-filtered vector search.

Everything lives in one ChromaDB collection. Each chunk is tagged with a `source`:
  strategy - options/investing education docs from ./knowledge
  journal  - your trades and journal notes
  news     - recent headlines per ticker
  filing   - SEC 10-K / 10-Q excerpts per ticker
Embeddings come from Chroma's built-in all-MiniLM-L6-v2 ONNX model, which runs locally (no API key).
"""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import chromadb

SOURCES = ("strategy", "journal", "news", "filing")


@dataclass
class Hit:
    text: str
    source: str
    title: str
    symbol: str | None
    url: str | None
    date: str | None
    score: float  # cosine similarity, higher is better

    def citation(self) -> str:
        parts = [self.source, self.title]
        if self.symbol:
            parts.append(self.symbol)
        if self.date:
            parts.append(self.date)
        return " | ".join(p for p in parts if p)


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 200) -> list[str]:
    """Split on paragraph boundaries, packing paragraphs into chunks of up to max_chars with a small overlap."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        while len(para) > max_chars:  # hard-split giant paragraphs (common in filings)
            cut = para.rfind(". ", 0, max_chars) + 1
            if cut < max_chars // 2:
                cut = max_chars
            pieces = para[:cut].strip()
            if current:
                chunks.append(current)
                current = ""
            chunks.append(pieces)
            start = max(cut - overlap, 1)
            start = para.find(" ", start) + 1 or start  # resume on a word boundary
            para = para[start:].strip()
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if current else ""
            current = f"{tail}\n\n{para}".strip() if tail else para
    if current:
        chunks.append(current)
    return chunks


def _id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


class KnowledgeBase:
    def __init__(self, path: Path | str | None = None, collection: str = "trading_kb"):
        client = chromadb.PersistentClient(path=str(path)) if path else chromadb.EphemeralClient()
        self.col = client.get_or_create_collection(collection, metadata={"hnsw:space": "cosine"})

    def add_document(self, text: str, source: str, key: str, title: str, symbol: str | None = None,
                     url: str | None = None, date: str | None = None, max_chars: int = 1200) -> int:
        """Chunk and upsert a document. `key` must be stable so re-ingesting replaces instead of duplicating."""
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        self.delete(source=source, key=key)
        chunks = chunk_text(text, max_chars=max_chars)
        if not chunks:
            return 0
        meta = {"source": source, "key": key, "title": title, "symbol": symbol or "", "url": url or "",
                "date": date or ""}
        # Prefix each chunk with its title so short chunks still embed with context.
        self.col.upsert(
            ids=[_id(source, key, str(i)) for i in range(len(chunks))],
            documents=[f"{title}\n\n{c}" for c in chunks],
            metadatas=[meta | {"chunk": i} for i in range(len(chunks))],
        )
        return len(chunks)

    def delete(self, source: str, key: str | None = None, symbol: str | None = None) -> None:
        clauses = [{"source": source}]
        if key:
            clauses.append({"key": key})
        if symbol:
            clauses.append({"symbol": symbol.upper()})
        self.col.delete(where=clauses[0] if len(clauses) == 1 else {"$and": clauses})

    def search(self, query: str, k: int = 6, sources: list[str] | None = None, symbol: str | None = None) -> list[Hit]:
        clauses = []
        if sources:
            clauses.append({"source": {"$in": list(sources)}})
        if symbol:
            clauses.append({"symbol": symbol.upper()})
        where = None if not clauses else clauses[0] if len(clauses) == 1 else {"$and": clauses}
        n = self.col.count()
        if n == 0:
            return []
        res = self.col.query(query_texts=[query], n_results=min(k, n), where=where)
        hits = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            hits.append(Hit(text=doc, source=meta["source"], title=meta["title"], symbol=meta["symbol"] or None,
                            url=meta["url"] or None, date=meta["date"] or None, score=round(1 - dist, 3)))
        return hits

    def stats(self) -> dict[str, int]:
        metas = self.col.get(include=["metadatas"])["metadatas"]
        counts = {s: 0 for s in SOURCES}
        for m in metas:
            counts[m["source"]] = counts.get(m["source"], 0) + 1
        return counts
