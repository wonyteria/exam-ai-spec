import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

os.environ["EXAMDNA_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)
h = {"X-Dev-User": "u1"}
c.post("/api/auth/dev-login", json={"user_id": "u1", "name": "Alice"})
r = c.post("/api/tenants", json={"name": "Academy A"}, headers=h)
tid = r.json()["id"]


def png():
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(t, d):
        return (
            struct.pack(">I", len(d))
            + t
            + d
            + struct.pack(">I", zlib.crc32(t + d))
        )

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * 4 for _ in range(4))
    return sig + ihdr + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


r = c.post(
    "/api/uploads",
    headers=h,
    files=[("files", ("p1.png", png(), "image/png"))],
)
print("upload", r.status_code, json.dumps(r.json())[:300])
if r.status_code != 200:
    sys.exit(1)

d = r.json()
doc_id = d.get("document_id") or d.get("id")
job_id = d.get("job_id")

r2 = c.get(f"/api/v1/tenants/{tid}/documents/{doc_id}", headers=h)
print("v1 doc", r2.status_code, json.dumps(r2.json())[:300])

r3 = c.get(f"/api/v1/tenants/{tid}/documents/{doc_id}/revisions", headers=h)
print("revs", r3.status_code, str(r3.json())[:300])

r4 = c.get(f"/api/jobs/{job_id}", headers=h)
print("legacy job", r4.status_code, str(r4.json())[:250])

r5 = c.get(f"/api/v1/tenants/{tid}/jobs/{job_id}/events", headers=h)
print("v1 events", r5.status_code, str(r5.text)[:300])

r6 = c.get(f"/api/v1/tenants/{tid}/documents/{doc_id}/eligibility", headers=h)
print("eligibility", r6.status_code, str(r6.json())[:400])
