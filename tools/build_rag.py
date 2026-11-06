"""Build the RAG index (V0.5): download models if needed, embed the
course packs, write rag.db.

  python -m tools.build_rag            # models -> models/, index -> rag.db
  python -m tools.build_rag --check    # also run the retrieval eval set

Models (MIT-licensed, BAAI): bge-large-zh-v1.5 embeddings (1024-dim) and
bge-reranker-large. They land in models/ and are never committed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODELS = {"bge-large-zh-v1.5": "BAAI/bge-large-zh-v1.5",
          "bge-reranker-large": "BAAI/bge-reranker-large"}


def ensure_models() -> None:
    from huggingface_hub import snapshot_download

    from app.rag import MODELS_DIR

    for local, repo in MODELS.items():
        target = MODELS_DIR / local
        if (target / "config.json").exists():
            print(f"model present: {local}")
            continue
        print(f"downloading {repo} -> {target} …")
        snapshot_download(repo_id=repo, local_dir=str(target),
                          ignore_patterns=["*.onnx", "onnx/*", "*.h5", "*.msgpack"])
        print(f"done: {local}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the RAG index")
    ap.add_argument("--check", action="store_true",
                    help="after building, run evals/rag_cases.json")
    args = ap.parse_args()

    ensure_models()
    from app import rag

    n = rag.build_index()
    print(f"index built: {n} chunks -> {rag.DB_PATH}")

    hits = rag.retrieve("为什么接上负载之后电压放大倍数会变小？")
    print("smoke query top hit:", hits[0]["source"] if hits else "NONE")
    if args.check:
        import json

        cases = json.loads((ROOT / "evals" / "rag_cases.json").read_text(encoding="utf-8"))
        passed = 0
        for case in cases:
            got = rag.retrieve(case["query"])
            if case["expect_source_contains"]:
                # RAG feeds the teacher an evidence *set*: the expected
                # concept must appear in the top-3, rank 1 alone is too strict
                ok = any(case["expect_source_contains"] in h["concept"]
                         for h in got[:3])
            else:
                ok = not got
            passed += ok
            print(f"  {'OK ' if ok else 'MISS'} {case['id']}: "
                  f"{got[0]['source'] if got else 'no-evidence'}")
        print(f"retrieval eval: {passed}/{len(cases)}")
        return 0 if passed == len(cases) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
