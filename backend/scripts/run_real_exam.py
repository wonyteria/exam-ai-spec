"""Run the real pipeline on the Simwon 2025 mid-2 exam fixture (5 pages).

Local-only: PaddleOCR runs on-device; no external AI calls. Evidence and
outputs land in a scratch data dir under backend/data/real_e2e/.
"""
import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("EXAMDNA_PADDLEOCR", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from document.models import Document
from jobs.models import Job
from jobs.runner import run_pipeline
from jobs.store import Store

ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLES = ROOT / "samples" / "simwon_2025_mid2"
DATA = ROOT / "backend" / "data" / "real_e2e"

def main() -> int:
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    store = Store(DATA)
    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = Path(store.job_dir(job.id)) / "uploads"
    uploads.mkdir(parents=True)
    for p in sorted(SAMPLES.glob("page*.jpg")):
        shutil.copy(p, uploads / p.name)

    run_pipeline(store, job.id)

    finished = store.get_job(job.id)
    result = store.load_document(doc.id)
    out = {
        "job_state": finished.state.value,
        "job_error": finished.error,
        "pages": len(result.pages),
        "questions": len(result.questions),
        "atus": len(result.all_atus()),
        "verification": result.verification.status,
        "gate": result.verification.gate,
    }
    for q in result.questions:
        out.setdefault("question_ids", []).append(q.id)
    for page in result.pages:
        census = {}
        for region in page.regions or []:
            k = region.get("kind", "?")
            census[k] = census.get(k, 0) + 1
        recon = {}
        for r in page.reconstruction or []:
            k = r.get("decision", "?")
            recon[k] = recon.get(k, 0) + 1
        out.setdefault("layer_census", []).append(
            {"page": page.index, "regions": census, "reconstruction": recon,
             "uncertain": len(page.uncertain_regions or []),
             "role": page.page_role}
        )
    report = DATA / "result.json"
    report.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str)[:4000])
    exports = store.export_dir(doc.id)
    print("\nEXPORTS:", [p.name for p in exports.glob("*")] if exports.exists() else "none")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
