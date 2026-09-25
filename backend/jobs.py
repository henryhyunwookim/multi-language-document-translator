"""Persistent file jobs with leases, idempotency, cancellation and checkpoints.

SQLite and artifacts must share a persistent local volume. Multiple worker
processes on that host coordinate through database leases; network filesystems
and independent Cloud Run replicas require a different store implementation.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid

TERMINAL = {"passed", "needs_review", "failed", "cancelled", "expired"}


class JobStore:
    def __init__(self, root: str | Path, *, ttl=86400, lease_seconds=60):
        if ttl <= 0 or lease_seconds <= 0:
            raise ValueError("Job retention and lease durations must be positive.")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "jobs.sqlite3"
        self.ttl = ttl
        self.lease_seconds = lease_seconds
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    created REAL NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, filename TEXT NOT NULL,
                    options TEXT NOT NULL, state TEXT NOT NULL, input_path TEXT NOT NULL,
                    artifact TEXT, report TEXT, checkpoint TEXT NOT NULL DEFAULT '{}',
                    progress INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                    owner TEXT, lease_until REAL NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS jobs_batch ON jobs(batch_id);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def authorize(self, batch_id: str, token: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if row is None or not secrets.compare_digest(row["token_hash"], self.token_hash(token)):
            raise PermissionError("Batch not found or access token invalid.")
        if row["expires"] <= time.time():
            raise TimeoutError("Batch and artifact access have expired.")

    def submit(self, batch_id: str, token: str, files: list[tuple[str, bytes]], options: dict):
        # A client-generated UUID plus a random capability token makes retrying
        # submission idempotent without exposing one user's batch to another.
        if str(uuid.UUID(batch_id)) != batch_id or len(token) < 32:
            raise ValueError("A canonical batch UUID and a strong access token are required.")
        fingerprint = hashlib.sha256(json.dumps({"files": [(name, hashlib.sha256(raw).hexdigest()) for name, raw in files],
                                                "options": options}, sort_keys=True).encode()).hexdigest()
        created_paths = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                previous = db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
                if previous:
                    if not secrets.compare_digest(previous["token_hash"], self.token_hash(token)):
                        raise PermissionError("Batch access token invalid.")
                    if previous["expires"] <= time.time():
                        raise TimeoutError("Batch expired; submit a new batch ID.")
                    if previous["fingerprint"] != fingerprint:
                        raise ValueError("Idempotency key was reused with different files or settings.")
                    db.execute("COMMIT")
                    return
                now = time.time()
                db.execute("INSERT INTO batches VALUES (?,?,?,?,?)", (batch_id, self.token_hash(token), fingerprint, now, now + self.ttl))
                for filename, raw in files:
                    identifier = str(uuid.uuid4())
                    safe_name = Path(filename.replace("\\", "/")).name
                    path = self.root / f"{identifier}.input"
                    path.write_bytes(raw)
                    created_paths.append(path)
                    db.execute("INSERT INTO jobs(id,batch_id,filename,options,state,input_path) VALUES (?,?,?,?,?,?)",
                               (identifier, batch_id, safe_name, json.dumps(options), "queued", str(path)))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                for path in created_paths:
                    path.unlink(missing_ok=True)
                raise

    def snapshot(self, batch_id: str, *, full_reports=False):
        with self.connect() as db:
            rows = db.execute("SELECT id,filename,state,progress,message,attempts,artifact,report FROM jobs WHERE batch_id=? ORDER BY rowid", (batch_id,)).fetchall()
        jobs = [{**dict(row), "artifact": bool(row["artifact"]), "report": json.loads(row["report"]) if row["report"] else None} for row in rows]
        if not full_reports:
            for job in jobs:
                if job["report"]:
                    job["report"] = {key: value for key, value in job["report"].items()
                                     if key in ("status", "checks", "findings", "model_calls", "repairs")}
        return {"id": batch_id, "jobs": jobs, "finished": bool(jobs) and all(job["state"] in TERMINAL for job in jobs)}

    def claim(self, owner: str, *, max_workers=2, per_provider=2):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recover expired leases. A surviving old worker cannot publish over
            # a new owner because all writes check the current ownership token.
            db.execute("UPDATE jobs SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'queued' END, owner=NULL WHERE state='running' AND lease_until<?", (now,))
            active = db.execute("SELECT options FROM jobs WHERE state='running'").fetchall()
            if len(active) >= max_workers:
                db.execute("COMMIT")
                return None
            rows = db.execute("SELECT jobs.* FROM jobs JOIN batches ON batches.id=jobs.batch_id WHERE jobs.state='queued' AND batches.expires>? ORDER BY jobs.rowid", (now,)).fetchall()
            for row in rows:
                provider = json.loads(row["options"])["provider"]
                if sum(json.loads(item["options"])["provider"] == provider for item in active) >= per_provider:
                    continue
                db.execute("UPDATE jobs SET state='running',owner=?,lease_until=?,attempts=attempts+1 WHERE id=?", (owner, now + self.lease_seconds, row["id"]))
                db.execute("COMMIT")
                return {**dict(row), "owner": owner, "options": json.loads(row["options"])}
            db.execute("COMMIT")
            return None

    def heartbeat(self, identifier: str, owner: str) -> bool:
        with self.connect() as db:
            changed = db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND owner=? AND state='running' AND cancel_requested=0 AND batch_id IN (SELECT id FROM batches WHERE expires>?)",
                                 (time.time() + self.lease_seconds, identifier, owner, time.time())).rowcount
        return bool(changed)

    def progress(self, identifier, owner, message, progress):
        with self.connect() as db:
            db.execute("UPDATE jobs SET message=?,progress=? WHERE id=? AND owner=? AND state='running'",
                       (str(message)[:2000], max(0, min(95, int(progress or 0))), identifier, owner))

    def checkpoint(self, identifier, owner, value=None):
        with self.connect() as db:
            if value is not None:
                if not db.execute("UPDATE jobs SET checkpoint=? WHERE id=? AND owner=? AND state='running' AND cancel_requested=0",
                                  (json.dumps(value), identifier, owner)).rowcount:
                    raise InterruptedError("Job lease lost or cancellation requested.")
            row = db.execute("SELECT checkpoint FROM jobs WHERE id=? AND owner=?", (identifier, owner)).fetchone()
        if row is None:
            raise InterruptedError("Job lease lost.")
        return json.loads(row["checkpoint"])

    def finish(self, identifier, owner, state, *, artifact=None, report=None, message=""):
        with self.connect() as db:
            return bool(db.execute("UPDATE jobs SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE ? END,artifact=CASE WHEN cancel_requested=1 THEN NULL ELSE ? END,report=?,message=?,progress=?,owner=NULL,lease_until=0 WHERE id=? AND owner=? AND state='running'",
                                   (state, artifact, json.dumps(report) if report else None, message[:2000], 100 if state in TERMINAL else 0, identifier, owner)).rowcount)

    def cancel(self, batch_id: str):
        with self.connect() as db:
            db.execute("UPDATE jobs SET cancel_requested=1,state=CASE WHEN state IN ('queued','waiting_credentials') THEN 'cancelled' ELSE state END WHERE batch_id=? AND state IN ('queued','running','waiting_credentials')", (batch_id,))

    def resume(self, batch_id: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,checkpoint FROM jobs WHERE batch_id=? AND state IN ('failed','cancelled','waiting_credentials')", (batch_id,)).fetchall()
            for row in rows:
                checkpoint = json.loads(row["checkpoint"])
                checkpoint["previous_model_calls"] = checkpoint.get("previous_model_calls", 0) + checkpoint.get("model_calls", 0)
                checkpoint["model_calls"] = 0
                db.execute("UPDATE jobs SET state='queued',cancel_requested=0,message='',progress=0,report=NULL,checkpoint=? WHERE id=?",
                           (json.dumps(checkpoint), row["id"]))
            db.execute("COMMIT")

    def artifact(self, batch_id, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND batch_id=?", (identifier, batch_id)).fetchone()
        if row is None or row["state"] not in ("passed", "needs_review") or not row["artifact"]:
            raise FileNotFoundError("Artifact is not ready.")
        return dict(row)

    def expire(self):
        with self.connect() as db:
            rows = db.execute("SELECT jobs.* FROM jobs JOIN batches ON batches.id=jobs.batch_id WHERE batches.expires<=? AND (jobs.input_path!='' OR jobs.artifact IS NOT NULL)", (time.time(),)).fetchall()
            db.execute("UPDATE jobs SET state='expired',cancel_requested=1,owner=NULL,checkpoint='{}',report=NULL WHERE state!='expired' AND batch_id IN (SELECT id FROM batches WHERE expires<=?)", (time.time(),))
        for row in rows:
            cleaned = True
            # This UUID prefix also finds artifacts written just before a worker
            # crashed, before it could commit their paths to the database.
            for candidate in self.root.glob(f"{row['id']}.*"):
                path = candidate.resolve()
                if path.parent == self.root:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        cleaned = False  # Retry locked files on the next sweep.
            if cleaned:
                with self.connect() as db:
                    db.execute("UPDATE jobs SET input_path='',artifact=NULL WHERE id=? AND state='expired'", (row["id"],))


class JobManager:
    def __init__(self, store: JobStore, processor, *, workers=2, per_provider=2):
        if not 1 <= workers <= 8 or not 1 <= per_provider <= workers:
            raise ValueError("Use 1–8 file workers and a per-provider limit within that range.")
        self.store, self.processor = store, processor
        self.workers, self.per_provider = workers, per_provider
        self.credentials = {}  # Never persist user API keys to the job database.
        self.stop_event = threading.Event()
        self.threads = []
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.threads:
                return
            for _ in range(self.workers):
                thread = threading.Thread(target=self._loop, daemon=True)
                thread.start()
                self.threads.append(thread)

    def close(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=2)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.store.expire()
                job = self.store.claim(str(uuid.uuid4()), max_workers=self.workers, per_provider=self.per_provider)
                if job is None:
                    self.stop_event.wait(0.25)
                    continue
                self._run(job)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Job scheduler error")
                self.stop_event.wait(1)

    def _run(self, job):
        identifier, owner = job["id"], job["owner"]
        key = self.credentials.get(job["batch_id"])
        if job["options"].get("user_key") and not key:
            self.store.finish(identifier, owner, "waiting_credentials", message="Re-enter the API key to resume after worker restart.")
            return
        cancelled = threading.Event()
        done = threading.Event()

        def heartbeat():
            while not done.wait(min(5, self.store.lease_seconds / 3)):
                if self.stop_event.is_set() or not self.store.heartbeat(identifier, owner):
                    cancelled.set()
                    return
        monitor = threading.Thread(target=heartbeat, daemon=True)
        monitor.start()
        path = None
        try:
            data, extension, report = self.processor(job, key, cancelled, self.store)
            if cancelled.is_set() or not self.store.heartbeat(identifier, owner):
                raise InterruptedError("Job cancelled or ownership lost.")
            state = report.get("status", "needs_review")
            if state not in ("passed", "needs_review", "failed"):
                raise ValueError("Processor returned an invalid quality state.")
            if state != "failed":
                path = self.store.root / f"{identifier}.{owner}{extension}"
                path.write_bytes(data)
            published = self.store.finish(identifier, owner, state, artifact=str(path) if path else None, report=report)
            if path:
                try:
                    retained = self.store.artifact(job["batch_id"], identifier)["artifact"] == str(path)
                except FileNotFoundError:
                    retained = False
                if not published or not retained:
                    path.unlink(missing_ok=True)
        except InterruptedError as exc:
            self.store.finish(identifier, owner, "queued" if self.stop_event.is_set() else "cancelled", message=str(exc))
            if path:
                path.unlink(missing_ok=True)
        except Exception as exc:
            from backend.quality.models import QualityFailure
            report = exc.report.to_dict() if isinstance(exc, QualityFailure) else None
            if isinstance(exc, QualityFailure):
                logging.getLogger(__name__).error('Job %s failed: %s', identifier, exc)
            else:
                logging.getLogger(__name__).exception('Job %s failed', identifier)
            self.store.finish(identifier, owner, "failed", report=report, message=str(exc))
        finally:
            done.set()
            monitor.join(timeout=2)
            if self.store.snapshot(job["batch_id"])["finished"]:
                self.credentials.pop(job["batch_id"], None)
