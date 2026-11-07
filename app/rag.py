"""Retrieval-augmented course Q&A (V0.5).

Pipeline: course-pack content -> chunks -> BGE-large-zh embeddings ->
sqlite-vec index -> top-k recall -> BGE-reranker-large re-ranking ->
evidence with sources for the teacher chat.

Design rules (from the project roadmap):
- answers in the teacher chat must cite these sources, and when retrieval
  finds nothing reliable the teacher says so instead of fabricating
  (see tutor.teacher_chat for how evidence is injected);
- models are local files under models/ (downloaded by tools/build_rag.py),
  never committed to git; the index rag.db is a build artifact too;
- if the optional dependencies or the index are missing, RAG quietly
  reports unavailable and the app behaves exactly as before.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("RAG_DB_PATH", ROOT / "rag.db"))
MODELS_DIR = Path(os.environ.get("RAG_MODELS_DIR", ROOT / "models"))
EMBED_MODEL = "bge-large-zh-v1.5"
RERANK_MODEL = "bge-reranker-large"
EMBED_DIM = 1024
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
# CrossEncoder.predict for the BGE reranker already returns probabilities
# (sentence-transformers applies the model's sigmoid activation — do NOT
# sigmoid again). Below this the evidence is treated as "not found"
# (calibrated on evals/rag_cases.json, see docs/rag.md)
MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.35"))

_embedder = None
_reranker = None


def _device() -> str:
    if os.environ.get("RAG_DEVICE"):
        return os.environ["RAG_DEVICE"]
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _load_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        path = MODELS_DIR / EMBED_MODEL
        _embedder = SentenceTransformer(str(path) if path.exists() else f"BAAI/{EMBED_MODEL}",
                                        device=_device())
    return _embedder


def _load_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        path = MODELS_DIR / RERANK_MODEL
        _reranker = CrossEncoder(str(path) if path.exists() else f"BAAI/{RERANK_MODEL}",
                                 device=_device())
    return _reranker


# ------------------------------------------------------------------ corpus
def build_chunks() -> list[dict]:
    """Turn the course packs into retrievable chunks with source labels."""
    from . import knowledge

    chunks: list[dict] = []
    for summary in knowledge.list_concepts():
        concept = knowledge.get_concept(summary["id"])
        title = concept["title"]
        chunks.append({
            "concept": concept["id"],
            "source": f"知识点「{title}」概述",
            "text": f"{title}。{concept['summary']} 要点：{'；'.join(concept['key_points'])}",
        })
        for code, text in concept["misconceptions"].items():
            chunks.append({
                "concept": concept["id"],
                "source": f"知识点「{title}」误区库",
                "text": f"常见误区（{code}）：{text}",
            })
        for stage in ("diagnose", "guided", "test"):
            for q in concept["questions"][stage]:
                parts = [q["prompt"]]
                if q.get("type", "mcq") == "mcq":
                    right = next((o["text"] for o in q["options"] if o.get("correct")), "")
                    if right:
                        parts.append(f"正确答案：{right}")
                if q.get("model_answer"):
                    parts.append(f"参考答案：{q['model_answer']}")
                if q.get("explanation"):
                    parts.append(f"解析：{q['explanation']}")
                chunks.append({
                    "concept": concept["id"],
                    "source": f"知识点「{title}」题目 {q['id']}",
                    "text": " ".join(parts),
                })
    return chunks


# ------------------------------------------------------------------ index
def _connect() -> sqlite3.Connection:
    import sqlite_vec

    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    return conn


def build_index(embedder=None) -> int:
    """(Re)build rag.db from the course packs. Returns the chunk count."""
    import sqlite_vec

    chunks = build_chunks()
    embedder = embedder or _load_embedder()
    vectors = embedder.encode([c["text"] for c in chunks], normalize_embeddings=True,
                              show_progress_bar=False)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = _connect()
    with conn:
        conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, concept TEXT, source TEXT, text TEXT)")
        conn.execute(f"CREATE VIRTUAL TABLE chunk_vec USING vec0(embedding float[{EMBED_DIM}])")
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            conn.execute("INSERT INTO chunks (id, concept, source, text) VALUES (?, ?, ?, ?)",
                         (i, chunk["concept"], chunk["source"], chunk["text"]))
            conn.execute("INSERT INTO chunk_vec (rowid, embedding) VALUES (?, ?)",
                         (i, sqlite_vec.serialize_float32(list(vec))))
    conn.close()
    return len(chunks)


def available() -> bool:
    return DB_PATH.exists()


# ------------------------------------------------------------------ query
def _tokens(text: str) -> list[str]:
    """BM25 tokens: Chinese character bigrams + ASCII words/symbols
    (formulas like Rc//RL and UCEQ survive as ASCII tokens)."""
    import re

    text = text.lower()
    toks = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text)
    han = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    toks += [a + b for a, b in zip(han, han[1:])]
    toks += han  # unigrams keep single-char concepts findable
    return toks


def bm25_ranking(query: str) -> list[dict]:
    """Okapi BM25 over all chunks (the corpus is small; for a much larger
    pack this ranking should be persisted at index-build time)."""
    import math

    if not available():
        return []
    conn = _connect()
    rows = conn.execute("SELECT id, concept, source, text FROM chunks").fetchall()
    conn.close()
    docs = [dict(r) for r in rows]
    doc_tokens = [_tokens(d["text"]) for d in docs]
    n = len(docs)
    avgdl = sum(len(t) for t in doc_tokens) / max(1, n)
    df: dict[str, int] = {}
    for toks in doc_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    q = set(_tokens(query))
    k1, b = 1.5, 0.75
    scored = []
    for d, toks in zip(docs, doc_tokens):
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            denom = tf[t] + k1 * (1 - b + b * len(toks) / max(1.0, avgdl))
            score += idf * (tf[t] * (k1 + 1)) / denom
        if score > 0:
            scored.append({**d, "bm25": score})
    return sorted(scored, key=lambda d: -d["bm25"])


def hybrid_candidates(query: str, k: int = 20, embedder=None) -> list[dict]:
    """Vector recall + BM25, fused with Reciprocal Rank Fusion.

    The two retrievers fail differently: vectors miss exact formula
    symbols, BM25 misses paraphrases. RRF needs no score calibration
    between them, which is why it is the fusion rule here.
    """
    vec = search(query, k=k, embedder=embedder)
    bm = bm25_ranking(query)[:k]
    fused: dict[str, dict] = {}
    scores: dict[str, float] = {}
    for rank, hit in enumerate(vec):
        key = hit["source"] + "|" + hit["text"][:40]
        fused[key] = hit
        scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
    for rank, hit in enumerate(bm):
        key = hit["source"] + "|" + hit["text"][:40]
        fused.setdefault(key, hit)
        scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
    return [fused[key] for key in sorted(scores, key=lambda kk: -scores[kk])[:k]]


def search(query: str, k: int = 20, embedder=None) -> list[dict]:
    """Vector recall only (no re-ranking)."""
    import sqlite_vec

    if not available():
        return []
    embedder = embedder or _load_embedder()
    qvec = embedder.encode([QUERY_INSTRUCTION + query], normalize_embeddings=True,
                           show_progress_bar=False)[0]
    conn = _connect()
    rows = conn.execute(
        "SELECT c.concept, c.source, c.text, v.distance FROM chunk_vec v JOIN chunks c ON c.id = v.rowid "
        "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
        (sqlite_vec.serialize_float32(list(qvec)), k),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def retrieve(query: str, top_n: int = 5, embedder=None, reranker=None) -> list[dict]:
    """Recall + re-rank; returns evidence above MIN_SCORE (possibly empty).

    An empty result is a *meaningful* outcome: the caller must not invent
    an answer from nothing (refusal policy, see docs/rag.md).
    """
    candidates = hybrid_candidates(query, k=20, embedder=embedder)
    if not candidates:
        return []
    reranker = reranker or _load_reranker()
    scores = reranker.predict([(query, c["text"]) for c in candidates])
    ranked = sorted(zip(candidates, scores), key=lambda p: -float(p[1]))
    out = []
    for cand, raw in ranked[:top_n]:
        prob = min(1.0, max(0.0, float(raw)))
        if prob < MIN_SCORE:
            continue
        out.append({"concept": cand["concept"], "source": cand["source"],
                    "text": cand["text"], "score": round(prob, 3)})
    return out
