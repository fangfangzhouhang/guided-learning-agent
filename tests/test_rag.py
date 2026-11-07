"""RAG plumbing tests with stub embedder/reranker — no model downloads,
no network. Retrieval *quality* is measured separately with the real
models (tools/build_rag.py --check, numbers in docs/rag.md)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rag, storage, tutor  # noqa: E402


class StubEmbedder:
    """Deterministic bag-of-words hashing vectors (dim must match)."""

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        import hashlib

        import numpy as np

        out = []
        for t in texts:
            v = np.zeros(rag.EMBED_DIM, dtype=np.float32)
            for ch in t:
                v[int(hashlib.md5(ch.encode()).hexdigest(), 16) % rag.EMBED_DIM] += 1.0
            n = np.linalg.norm(v) or 1.0
            out.append(v / n)
        return np.array(out)


class StubReranker:
    def __init__(self, score):
        self.score = score

    def predict(self, pairs):
        return [self.score] * len(pairs)


@pytest.fixture()
def rag_db(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "DB_PATH", tmp_path / "rag.db")
    n = rag.build_index(embedder=StubEmbedder())
    assert n > 10
    return n


def test_search_returns_candidates(rag_db):
    rows = rag.search("放大倍数", embedder=StubEmbedder())
    assert rows and "source" in rows[0] and "concept" in rows[0]


def test_retrieve_respects_threshold(rag_db):
    # reranker probabilities: 0.0 -> no evidence (refusal path); 1.0 -> kept
    assert rag.retrieve("放大倍数", embedder=StubEmbedder(),
                        reranker=StubReranker(0.0)) == []
    hits = rag.retrieve("放大倍数", embedder=StubEmbedder(),
                        reranker=StubReranker(1.0))
    assert hits and hits[0]["score"] > 0.9 and "source" in hits[0]


def test_chat_injects_sources(monkeypatch, tmp_path):
    old = storage.DB_PATH
    storage.DB_PATH = tmp_path / "chat.db"
    storage.init_db()
    try:
        monkeypatch.setattr(rag, "available", lambda: True)
        monkeypatch.setattr(rag, "retrieve", lambda msg: [
            {"concept": "ce_amp", "source": "知识点「共射放大电路」题目 ce_g3",
             "text": "接 RL 后 Rc//RL 变小", "score": 0.99}])
        captured = {}

        def fake_teacher(system, history):
            captured["system"] = system
            return "回答[1]"

        monkeypatch.setattr(tutor.llm, "teacher_chat", fake_teacher)
        out = tutor.teacher_chat("stu", "为什么接负载增益变小？")
        assert out["sources"][0]["source"].startswith("知识点")
        assert "检索到的课程资料" in captured["system"]
        assert "ce_g3" in captured["system"]
    finally:
        storage.DB_PATH = old


def test_bm25_finds_exact_terms(rag_db):
    ranked = rag.bm25_ranking("放大倍数公式")
    assert ranked and ranked[0]["bm25"] > 0


def test_hybrid_returns_candidates(rag_db):
    hits = rag.hybrid_candidates("为什么放大倍数变小", embedder=StubEmbedder())
    assert hits and "source" in hits[0]


def test_retrieval_query_rewriting(tmp_path):
    old = storage.DB_PATH
    storage.DB_PATH = tmp_path / "rq.db"
    storage.init_db()
    try:
        storage.add_chat_message("s", "user", "为什么接上负载后放大倍数会变小？")
        storage.add_chat_message("s", "assistant", "因为 Rc//RL 变小…")
        storage.add_chat_message("s", "user", "那它对输出电阻有影响吗？")
        q = tutor._retrieval_query("s", "那它对输出电阻有影响吗？")
        assert "放大倍数" in q and "输出电阻" in q  # previous question prepended
        long_q = "请详细解释一下分压式偏置电路稳定静态工作点的完整过程"
        assert tutor._retrieval_query("s", long_q) == long_q  # self-contained: untouched
    finally:
        storage.DB_PATH = old


def test_chat_without_evidence_stays_plain(monkeypatch, tmp_path):
    old = storage.DB_PATH
    storage.DB_PATH = tmp_path / "chat2.db"
    storage.init_db()
    try:
        monkeypatch.setattr(rag, "available", lambda: False)
        monkeypatch.setattr(tutor.llm, "teacher_chat", lambda s, h: "普通回答")
        out = tutor.teacher_chat("stu", "随便问问")
        assert out["sources"] == []
    finally:
        storage.DB_PATH = old
