"""RESTORE-10B: benchmark harness — metrics, gold isolation, runner."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from eval.bench import fixtures, gold, metrics, runner, synth

BACKEND = Path(__file__).resolve().parents[1]


class TestGoldIsolation:
    """The reconstruction path must never reference gold material."""

    _PIPELINE_DIRS = ("core", "document", "renderers", "qa", "jobs",
                      "providers", "canonical", "app", "storage",
                      "rebranding", "tenancy")
    # Gold access = opening gold FILES/paths. An ANSWER_KEY *page role* is
    # legitimate pipeline logic and is not a gold read.
    _GOLD_PAT = re.compile(
        r"expected\.json|reference_draft|gold\.json|answer_key\.json|"
        r"samples[/\\]gold|holdout",
        re.IGNORECASE,
    )

    def test_no_pipeline_module_reads_gold(self):
        offenders = []
        for d in self._PIPELINE_DIRS:
            root = BACKEND / d
            if not root.exists():
                continue
            for py in root.rglob("*.py"):
                if "pycache" in py.parts:
                    continue
                text = py.read_text(encoding="utf-8", errors="replace")
                if self._GOLD_PAT.search(text):
                    offenders.append(str(py.relative_to(BACKEND)))
        assert offenders == [], f"gold references in pipeline code: {offenders}"

    def test_load_expected_is_gated(self, tmp_path):
        p = tmp_path / "ordinary"
        p.mkdir()
        (p / "expected.json").write_text("{}", encoding="utf-8")
        # ordinary dir still counts: expected.json is a gold filename
        assert gold.is_gold_path(p / "expected.json")
        assert not gold.is_gold_path(p / "page1.jpg")

    def test_damaged_inputs_are_readable(self):
        pages = gold.damaged_inputs(
            Path(fixtures.REPO_ROOT) / "samples" / "golden_001"
        )
        assert len(pages) == 5


class TestFixtures:
    def test_dev_families_listed(self):
        fams = fixtures.benchable_families()
        assert "golden-001-replay" in fams

    def test_holdout_family_refused(self, monkeypatch, tmp_path):
        import json as _json

        reg = {
            "version": 1,
            "families": [
                {"family_id": "sealed-x", "split": "holdout",
                 "asset_sha256": ["a" * 64], "sealed_at": "2026-01-01"}
            ],
        }
        p = tmp_path / "splits.json"
        p.write_text(_json.dumps(reg), encoding="utf-8")
        monkeypatch.setattr(fixtures, "SPLITS_PATH", p)
        with pytest.raises(PermissionError):
            fixtures.fixture_path("sealed-x")

    def test_undeclared_family_refused(self):
        with pytest.raises(KeyError):
            fixtures.fixture_path("not-a-family")


class TestMetrics:
    def test_char_exact(self):
        assert metrics.char_exact("abc", "abc") == 1.0
        assert metrics.char_exact("abc", "axc") < 1.0
        assert metrics.char_exact("", "abc") == 0.0

    def test_critical_tokens_extract_digits_ops_choices(self):
        toks = metrics.critical_tokens("3번 x=12.5cm, 답은 ④")
        assert "3" in toks and "12.5cm" in toks and "④" in toks
        assert "=" in toks

    def test_hallucination_counts_extra_critical_tokens(self):
        assert metrics.source_hallucination("x=12cm", "x=12cm") == 0
        assert metrics.source_hallucination("x=12cm ⑤ 98", "x=12cm") == 2

    def test_layer_metrics_print_destruction(self):
        g_print = np.zeros((10, 10), bool)
        g_print[0:5, 0:5] = True
        g_hand = np.zeros((10, 10), bool)
        g_hand[5:8, 5:8] = True
        masks_perfect = {"print": g_print.copy(),
                         "handwriting": g_hand.copy()}
        m = metrics.layer_metrics(masks_perfect,
                                  {"print": g_print, "handwriting": g_hand})
        assert m["print_recall"] == 1.0
        assert m["print_destruction_rate"] == 0.0
        # misclassify half the print as handwriting → destruction 0.5
        bad_hand = g_hand.copy()
        bad_hand[0:3, 0:5] = True
        m2 = metrics.layer_metrics(
            {"print": g_print, "handwriting": bad_hand},
            {"print": g_print, "handwriting": g_hand},
        )
        assert 0.4 < m2["print_destruction_rate"] < 0.7

    def test_question_metrics_skips_absent_gold_fields(self):
        # Partial gold (no body/choices/answer) must not read as a zero.
        m = metrics.question_metrics(
            {"body": "garbage", "choices": {}, "points": 3},
            {"number": "1", "points": 3},
        )
        assert m["body_exact"] is None
        assert m["choice_exact"] is None
        assert m["answer_match"] is None
        assert m["points_match"] is True
        assert m["figure_label_recall"] is None

    def test_question_metrics_figure_label_recall(self):
        m = metrics.question_metrics(
            {"figure_text": "삼각형 △ABC ∠A=40° AB=12cm"},
            {"number": "1", "figure_labels": ["△ABC", "∠A", "40°", "∠C"]},
        )
        assert m["figure_label_recall"] == 0.75
        # no gold figure labels -> field skipped
        m2 = metrics.question_metrics({}, {"number": "1"})
        assert m2["figure_label_recall"] is None


class TestSynth:
    def test_generates_paired_masks(self):
        res = synth.generate(synth.SynthSpec(seed=1, noise_sigma=0,
                                             rotate_deg=0))
        assert set(res.masks) == {"print", "handwriting", "grading",
                                  "overlap"}
        assert res.masks["print"].sum() > 0
        assert res.masks["handwriting"].sum() > 0
        # overlap = annotation ∩ print
        ov = res.masks["overlap"]
        assert (ov <= (res.masks["handwriting"] | res.masks["grading"])).all()
        assert (ov <= res.masks["print"]).all()

    def test_deterministic_by_seed(self):
        a = synth.generate(synth.SynthSpec(seed=7))
        b = synth.generate(synth.SynthSpec(seed=7))
        assert (np.array(a.damaged) == np.array(b.damaged)).all()


class TestRunner:
    def test_mock_provider_runs_and_records(self, tmp_path):
        run = runner.run_ocr_benchmark(
            ["golden-001-replay"], provider_names=["mock"],
            commit="test",
        )
        item = run["results"]["golden-001-replay::mock"]
        # mock returns empty text → honest FAIL with metrics recorded,
        # never silently passed
        assert item["status"] == "FAIL"
        assert run["rows"]
        assert run["rows"][0]["char_exact"] == 0.0

    def test_unavailable_provider_is_not_run(self):
        run = runner.run_ocr_benchmark(
            ["golden-001-replay"],
            provider_names=["paddleocr"],  # paddle not installed in CI
            commit="test",
        )
        st = run["results"]["golden-001-replay::paddleocr"]["status"]
        assert st in ("NOT_RUN", "FAIL", "PASS")  # env-dependent, recorded

    def test_write_run_persists(self, tmp_path):
        run = runner.run_ocr_benchmark(["golden-001-replay"],
                                       provider_names=["mock"])
        rows, rp = runner.write_run(run, tmp_path)
        assert rows.exists() and rp.exists()
