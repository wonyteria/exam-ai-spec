"""RESTORE-09: family-level split integrity, leakage control, release gate."""
from __future__ import annotations

from pathlib import Path

import pytest

from eval import report, splits

REPO_SPLITS = (
    Path(__file__).resolve().parents[2]
    / "docs" / "handoff" / "evidence" / "CORPUS_SPLITS.json"
)


def _reg(families):
    return {"version": 1, "families": families}


def _fam(fid, split, assets=("a1",), sealed_at=None):
    f = {"family_id": fid, "split": split, "asset_sha256": list(assets)}
    if sealed_at:
        f["sealed_at"] = sealed_at
    return f


def _run(items=("q1", "q2"), split="holdout"):
    return report.new_run(
        commit="abc", benchmark_version="1.0", split_hash="deadbeef",
        provider_config="mock", worker_version="w1",
        items=list(items), split=split,
    )


class TestSplits:
    def test_clean_registry(self):
        reg = _reg([
            _fam("gyenam-2025-1", "dev", ("a1", "a2")),
            _fam("simwon-2025-1", "holdout", ("h1",), sealed_at="2025-01-01"),
        ])
        assert splits.validate_registry(reg) == []

    def test_family_in_two_splits_is_an_error(self):
        reg = _reg([
            _fam("exam-a", "dev"),
            _fam("exam-a", "holdout", sealed_at="2025-01-01"),
        ])
        assert any("exam-a" in e for e in splits.validate_registry(reg))

    def test_same_hash_in_holdout_and_dev_is_leakage(self):
        shared = "f" * 64
        reg = _reg([
            _fam("exam-a", "dev", (shared,)),
            _fam("exam-b", "holdout", (shared,), sealed_at="2025-01-01"),
        ])
        assert any("leaks" in e for e in splits.validate_registry(reg))

    def test_holdout_requires_sealed_at(self):
        reg = _reg([_fam("exam-b", "holdout", ("h1",))])
        assert any("sealed_at" in e for e in splits.validate_registry(reg))

    def test_repo_registry_is_clean(self):
        reg = splits.load_registry(REPO_SPLITS)
        assert splits.validate_registry(reg) == []

    def test_registry_hash_is_stable(self, tmp_path):
        reg = _reg([_fam("exam-a", "dev")])
        p = tmp_path / "splits.json"
        import json
        p.write_text(json.dumps(reg), encoding="utf-8")
        assert splits.registry_hash(splits.load_registry(p)) == splits.registry_hash(reg)


class TestEvalRun:
    def test_post_hoc_items_forbidden(self):
        run = _run(("q1",))
        with pytest.raises(KeyError):
            report.record(run, "q99", "PASS")

    def test_undeclared_results_become_not_run(self):
        run = _run(("q1", "q2"))
        report.record(run, "q1", "PASS")
        report.finalize(run)
        assert run["results"]["q2"]["status"] == "NOT_RUN"

    def test_summary_separates_outcomes(self):
        run = _run(("a", "b", "c", "d"))
        report.record(run, "a", "PASS")
        report.record(run, "b", "FAIL", critical=True)
        report.record(run, "c", "REVIEW")
        report.finalize(run)
        s = report.summarize(run)
        assert s["counts"] == {"PASS": 1, "FAIL": 1, "REVIEW": 1, "REJECT": 0,
                               "NOT_RUN": 1}
        assert s["critical_failures"] == 1
        # abstention counts against the rate, not for it
        assert s["auto_exact_rate"] == pytest.approx(0.25)


class TestReleaseGate:
    def test_clean_holdout_run_passes(self):
        run = _run(("a", "b"))
        report.record(run, "a", "PASS")
        report.record(run, "b", "PASS")
        report.finalize(run)
        verdict = report.evaluate_release_gate(run)
        assert verdict["release"] == "PASS"

    def test_not_run_never_counts_as_pass(self):
        run = _run(("a", "b"))
        report.record(run, "a", "PASS")
        report.finalize(run)  # b → NOT_RUN
        verdict = report.evaluate_release_gate(run)
        assert verdict["release"] == "BLOCKED"
        assert any("NOT_RUN" in b for b in verdict["blockers"])

    def test_dev_split_cannot_gate_release(self):
        run = _run(("a",), split="dev")
        report.record(run, "a", "PASS")
        report.finalize(run)
        assert report.evaluate_release_gate(run)["release"] == "BLOCKED"

    def test_critical_review_blocks(self):
        run = _run(("a",))
        report.record(run, "a", "REVIEW", critical=True)
        verdict = report.evaluate_release_gate(run)
        assert verdict["release"] == "BLOCKED"
        assert any("critical" in b for b in verdict["blockers"])

    def test_missing_metadata_blocks(self):
        run = _run(("a",))
        run["worker_version"] = ""
        report.record(run, "a", "PASS")
        verdict = report.evaluate_release_gate(run)
        assert verdict["release"] == "BLOCKED"
        assert any("metadata" in b for b in verdict["blockers"])
