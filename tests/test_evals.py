"""CI hook for the eval harness: the deterministic teaching cases must
always pass. Judge-agreement numbers are reported by evals/run_evals.py,
not asserted here (they measure the judge, not the engine)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("run_evals", ROOT / "evals" / "run_evals.py")
run_evals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_evals)


def test_teaching_cases_all_pass(tmp_path):
    result = run_evals.run_teaching_cases(db_path=tmp_path / "evals.db")
    failures = [c for c in result["cases"] if not c["passed"]]
    assert not failures, f"teaching cases failed: {failures}"
