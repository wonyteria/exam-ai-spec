from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, documents, jobs, uploads, v1

app = FastAPI(title="ExamDNA API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(auth.router)
app.include_router(v1.router)
app.include_router(uploads.router)
app.include_router(jobs.router)
app.include_router(documents.router)


@app.get("/api/health")
def health():
    return {"ok": True}
