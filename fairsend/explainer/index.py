"""Chunk the vetted source library and build a FAISS index with a local sentence-transformers model."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from fairsend.config import CORPUS_DIR, INDEX_DIR, settings

MAX_WORDS = 200


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_id: str
    title: str
    publisher: str
    url: str
    section: str
    text: str


def parse_document(path: Path) -> tuple[dict, str]:
    raw = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing frontmatter")
    return yaml.safe_load(m.group(1)), m.group(2)


def _split_long(paragraphs: list[str]) -> list[str]:
    """Group paragraphs into pieces of at most MAX_WORDS words (a single long paragraph stays whole)."""
    pieces, current, words = [], [], 0
    for p in paragraphs:
        n = len(p.split())
        if current and words + n > MAX_WORDS:
            pieces.append("\n\n".join(current))
            current, words = [], 0
        current.append(p)
        words += n
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def chunk_corpus(corpus_dir: Path = CORPUS_DIR) -> list[Chunk]:
    chunks = []
    for path in sorted(corpus_dir.glob("*.md")):
        meta, body = parse_document(path)
        sections = re.split(r"^## +(.+)$", body, flags=re.M)
        # sections = [preamble, heading1, text1, heading2, text2, ...]
        pairs = [("Overview", sections[0])] + list(zip(sections[1::2], sections[2::2]))
        for heading, text in pairs:
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
            for i, piece in enumerate(_split_long(paragraphs)):
                chunks.append(Chunk(
                    chunk_id=f"{meta['id']}#{len(chunks)}", source_id=meta["id"], title=meta["title"],
                    publisher=meta.get("publisher", ""), url=meta.get("url", ""),
                    section=heading.strip() + (f" (part {i + 1})" if i else ""), text=piece,
                ))
    return chunks


def _corpus_hash(corpus_dir: Path) -> str:
    h = hashlib.sha256(settings.embed_model.encode())
    for p in sorted(corpus_dir.glob("*.md")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


@lru_cache(maxsize=1)
def embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.embed_model, device="cpu")


def embed(texts: list[str]) -> np.ndarray:
    vecs = embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
    return np.asarray(vecs, dtype="float32")


class Index:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray):
        # PyTorch must load before FAISS: on macOS both ship an OpenMP runtime, and importing FAISS first makes the
        # first query embedding crash the process.
        embedder()
        import faiss
        self.chunks = chunks
        self.faiss = faiss.IndexFlatIP(vectors.shape[1])  # inner product on unit vectors = cosine
        self.faiss.add(vectors)

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        q = embed([query])
        scores, ids = self.faiss.search(q, k)
        return [(self.chunks[i], float(s)) for s, i in zip(scores[0], ids[0]) if i >= 0]


def build(corpus_dir: Path = CORPUS_DIR, index_dir: Path = INDEX_DIR, force: bool = False) -> Index:
    """Load the cached index, or rebuild it when the corpus or embedding model changed."""
    key = _corpus_hash(corpus_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    vec_path, meta_path = index_dir / f"vectors-{key}.npy", index_dir / f"chunks-{key}.json"
    if not force and vec_path.exists() and meta_path.exists():
        chunks = [Chunk(**c) for c in json.loads(meta_path.read_text())]
        return Index(chunks, np.load(vec_path))
    chunks = chunk_corpus(corpus_dir)
    if not chunks:
        raise RuntimeError(f"No corpus documents in {corpus_dir}")
    vectors = embed([f"{c.title}. {c.section}. {c.text}" for c in chunks])
    for old in index_dir.glob("*-*.npy"):
        old.unlink()
    for old in index_dir.glob("chunks-*.json"):
        old.unlink()
    np.save(vec_path, vectors)
    meta_path.write_text(json.dumps([asdict(c) for c in chunks]))
    return Index(chunks, vectors)


@lru_cache(maxsize=1)
def default_index() -> Index:
    return build()
