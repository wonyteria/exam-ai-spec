"""Real service E2E — HTTP upload -> worker -> canonical revision ->
artifacts -> review items -> eligibility, on the Simwon fixture.

Runs the actual API (uvicorn) and the production worker path
(jobs.worker.run_once), not the legacy run_pipeline shortcut.
Local-only providers: PaddleOCR + EasyOCR, no external calls.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("EXAMDNA_PADDLEOCR", "1")
os.environ.setdefault("EXAMDNA_PADDLE_PAGE", "1")
os.environ.setdefault("EXAMDNA_EASYOCR", "1")

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
SAMPLES = ROOT / "samples" / "simwon_2025_mid2"
DATA = BACKEND / "data" / "service_e2e"
PORT = 8871
BASE = f"http://127.0.0.1:{PORT}"
HEADERS = {"x-dev-user": "e2e@local", "x-dev-tenant": "e2e-tenant"}


def _req(method: str, path: str, body=None, files=None):
    if files:
        boundary = "----e2e"
        parts = []
        for name, blob in files:
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="files"; '
                    f'filename="{name}"\r\n'
                    "Content-Type: image/jpeg\r\n\r\n"
                ).encode() + blob + b"\r\n"
            )
        payload = b"".join(parts) + b"--" + boundary.encode() + b"--\r\n"
        req = urllib.request.Request(
            BASE + path, data=payload, method=method,
            headers={
                **HEADERS,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
    else:
        payload = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            BASE + path, data=payload, method=method,
            headers={**HEADERS, "Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:500])
        raise


def main() -> int:
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    env = dict(os.environ, EXAMDNA_DATA=str(DATA))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=BACKEND, env=env,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("server failed to start")
            return 1

        # Dev auth: create the academy first — membership is what makes
        # x-dev-tenant a valid active tenant.
        tenant = _req("POST", "/api/tenants", {"name": "E2E 학원"})
        HEADERS["x-dev-tenant"] = tenant["id"]
        print("TENANT:", tenant["id"])

        files = [(p.name, p.read_bytes()) for p in sorted(SAMPLES.glob("page*.jpg"))]
        up = _req("POST", "/api/uploads", files=files)
        doc_id = up["document_id"]
        job_id = up.get("job_id") or up.get("job", {}).get("id")
        print("UPLOAD:", json.dumps(up, ensure_ascii=False)[:300])

        # The upload handler spawns the production worker (run_once) inside
        # the server process — poll the job until it reaches a terminal state.
        # Real OCR (PaddleOCR+EasyOCR) on 5 pages takes ~10 min on CPU.
        terminal = {"COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"}
        state = "RUNNING"
        for _ in range(480):
            j = _req("GET", f"/api/jobs/{job_id}")
            state = j["state"]
            if state in terminal:
                break
            time.sleep(5)
        print("JOB STATE:", state, "| error:", j.get("error"))
        last_events = [e["message"] for e in j.get("events", [])[-5:]]
        print("LAST EVENTS:", json.dumps(last_events, ensure_ascii=False)[:500])

        revs = _req("GET", f"/api/v1/tenants/{HEADERS['x-dev-tenant']}/documents/{doc_id}/revisions")
        print("REVISIONS:", len(revs["data"]["revisions"]))
        issues = _req("GET", f"/api/v1/tenants/{HEADERS['x-dev-tenant']}/documents/{doc_id}/issues")
        print("ISSUES:", len(issues["data"]["issues"]))
        elig = _req("GET", f"/api/v1/tenants/{HEADERS['x-dev-tenant']}/documents/{doc_id}/eligibility")
        print("ELIGIBILITY:", json.dumps(elig["data"], ensure_ascii=False)[:400])
        review = _req("GET", f"/api/documents/{doc_id}/review-items")
        print("REVIEW ITEMS:", len(review["items"]),
              "| missing:", review["missing_numbers"])

        # Artifact inventory (per-format under eligibility.formats) + download.
        artifacts = []
        for fmt, block in elig["data"].get("formats", {}).items():
            for a in block.get("artifacts", []):
                artifacts.append({**a, "format": fmt})
        print("ARTIFACTS:", [(a.get("format"), a.get("state")) for a in artifacts])
        downloads = {}
        for a in artifacts:
            try:
                req = urllib.request.Request(
                    BASE + f"/api/v1/artifacts/{a['id']}/download?purpose=draft",
                    headers=HEADERS)
                with urllib.request.urlopen(req) as r:
                    downloads[a["id"]] = len(r.read())
            except urllib.error.HTTPError as e:
                downloads[a["id"]] = f"HTTP {e.code}"
        print("DOWNLOADS:", downloads)

        evidence = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fixture": "simwon_2025_mid2 (5 pages, real photographed exam)",
            "tenant_id": HEADERS["x-dev-tenant"],
            "document_id": doc_id,
            "job_id": job_id,
            "job_state": state,
            "revisions": len(revs["data"]["revisions"]),
            "issues": len(issues["data"]["issues"]),
            "content_ready": elig["data"].get("content_ready"),
            "content_checks": {
                c["check_kind"]: c["state"]
                for c in elig["data"].get("content_checks", [])
            },
            "review_items": len(review["items"]),
            "missing_numbers": review["missing_numbers"],
            "artifacts": [
                {k: a.get(k) for k in ("id", "format", "state", "sha256")}
                for a in artifacts
            ],
            "artifact_downloads": downloads,
        }
        out = ROOT / "docs" / "handoff" / "evidence" / "service_e2e_simwon.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        print("EVIDENCE:", out)
        return 0
    finally:
        server.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
