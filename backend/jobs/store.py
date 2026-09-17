from __future__ import annotations

import asyncio
import json
from pathlib import Path

from document.models import Document
from .models import Job, JobEvent


class Store:
    """File-backed persistence. Jobs/documents are JSON under data/."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        for sub in ("uploads", "documents", "jobs", "exports"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        self._subscribers: dict[str, list[asyncio.Queue[JobEvent]]] = {}
        self._jobs: dict[str, Job] = {}

    def save_document(self, doc: Document) -> Path:
        path = self.data_dir / "documents" / f"{doc.id}.json"
        path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_document(self, doc_id: str) -> Document:
        path = self.data_dir / "documents" / f"{doc_id}.json"
        return Document.model_validate_json(path.read_text(encoding="utf-8"))

    def document_path(self, doc_id: str) -> Path:
        return self.data_dir / "documents" / f"{doc_id}.json"

    def create_job(self, job: Job) -> Job:
        self._jobs[job.id] = job
        self._persist(job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        if job_id in self._jobs:
            return self._jobs[job_id]
        path = self.data_dir / "jobs" / f"{job_id}.json"
        if path.exists():
            job = Job.model_validate_json(path.read_text(encoding="utf-8"))
            self._jobs[job.id] = job
            return job
        return None

    def update_job(self, job: Job) -> None:
        self._jobs[job.id] = job
        self._persist(job)

    def emit(self, job: Job, stage: str, message: str, level: str = "info") -> None:
        event = JobEvent(stage=stage, message=message, level=level)
        job.events.append(event)
        self._persist(job)
        for queue in self._subscribers.get(job.id, []):
            queue.put_nowait(event)

    def subscribe(self, job_id: str) -> asyncio.Queue[JobEvent]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue()
        self._subscribers.setdefault(job_id, []).append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[JobEvent]) -> None:
        subs = self._subscribers.get(job_id, [])
        if queue in subs:
            subs.remove(queue)

    def job_dir(self, job_id: str) -> Path:
        path = self.data_dir / "jobs" / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def export_dir(self, doc_id: str) -> Path:
        path = self.data_dir / "exports" / doc_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _persist(self, job: Job) -> None:
        path = self.data_dir / "jobs" / f"{job.id}.json"
        path.write_text(
            json.dumps(job.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
