from contextlib import contextmanager
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .config import Config
from .models import JobState, ResourceState


def now():
    return datetime.now(UTC).isoformat()


def digest(data: bytes):
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, root: str | Path = ".siteprep"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, seed TEXT NOT NULL, config TEXT NOT NULL,
                status TEXT NOT NULL, created TEXT NOT NULL, finished TEXT,
                cancel INTEGER DEFAULT 0, termination TEXT, warnings TEXT DEFAULT '[]',
                elapsed REAL DEFAULT 0, owner_pid INTEGER
            );
            CREATE TABLE IF NOT EXISTS resources (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                url TEXT NOT NULL, parent TEXT, depth INTEGER NOT NULL, kind TEXT NOT NULL,
                state TEXT NOT NULL, reason TEXT, record TEXT,
                UNIQUE(job_id, url)
            );
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL, resource_id TEXT,
                metadata TEXT NOT NULL, path TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY, job_id TEXT, url TEXT, method TEXT,
                timestamp TEXT, status INTEGER, reason TEXT, bytes INTEGER DEFAULT 0
            );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "jobs.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, seed: str, config: Config):
        job_id = uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs(id, seed, config, status, created) VALUES(?,?,?,?,?)",
                (job_id, seed, config.model_dump_json(), "created", now()),
            )
        (self.job_dir(job_id) / "raw").mkdir(parents=True)
        return job_id

    def job_dir(self, job_id):
        # IDs never come from a URL or an unchecked filesystem path.
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("Invalid job ID")
        return self.root / job_id

    def job(self, job_id) -> JobState:
        self.job_dir(job_id)
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown job: {job_id}")
        return dict(row)

    def jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY created DESC")]

    def update_job(self, job_id, **values):
        allowed = {"status", "finished", "cancel", "termination", "warnings", "elapsed", "owner_pid"}
        if not values.keys() <= allowed:
            raise ValueError("Invalid job field")
        with self.connect() as db:
            db.execute(
                f"UPDATE jobs SET {','.join(k + '=?' for k in values)} WHERE id=?", (*values.values(), job_id)
            )

    def cancel(self, job_id):
        job = self.job(job_id)
        if job["status"] == "running":
            self.update_job(job_id, cancel=1)
        elif job["status"] == "created":
            self.update_job(job_id, cancel=1, status="cancelled", termination="cancelled", finished=now())

    def enqueue(self, job_id, url, parent=None, depth=0, kind="page", state="queued", reason=None):
        resource_id = hashlib.sha256(f"{job_id}:{url}".encode()).hexdigest()[:32]
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO resources(id,job_id,url,parent,depth,kind,state,reason) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (resource_id, job_id, url, parent, depth, kind, state, reason),
            )
        return resource_id

    def resources(self, job_id, state=None):
        with self.connect() as db:
            sql = "SELECT * FROM resources WHERE job_id=?"
            params = [job_id]
            if state:
                sql += " AND state=?"
                params.append(state)
            return [dict(r) for r in db.execute(sql + " ORDER BY rowid", params)]

    def update_resource(self, resource_id, state: ResourceState, reason=None, record=None):
        with self.connect() as db:
            db.execute(
                "UPDATE resources SET state=?,reason=?,record=COALESCE(?,record) WHERE id=?",
                (state, reason, json.dumps(record, ensure_ascii=False) if record else None, resource_id),
            )

    def save_source(self, job_id, resource_id, body, metadata):
        source_id = uuid4().hex
        relative = f"raw/{source_id}.bin"
        (self.job_dir(job_id) / relative).write_bytes(body)
        metadata = {**metadata, "source_id": source_id, "content_hash": digest(body), "size": len(body)}
        with self.connect() as db:
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?)",
                (source_id, job_id, resource_id, json.dumps(metadata), relative),
            )
        return {**metadata, "path": relative, "resource_id": resource_id}

    def save_response(self, job_id, resource_id, response, **metadata):
        values = {**response.metadata(), **metadata}
        if response.wire_body is not None:
            wire = self.save_source(
                job_id,
                resource_id,
                response.wire_body,
                {**values, "role": "encoded_transport", "body_representation": "encoded_http_entity"},
            )
            values["wire_source_id"] = wire["source_id"]
        return self.save_source(job_id, resource_id, response.body, values)

    def sources(self, job_id):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM sources WHERE job_id=? ORDER BY rowid", (job_id,)).fetchall()
        return [
            {**json.loads(r["metadata"]), "path": r["path"], "resource_id": r["resource_id"]} for r in rows
        ]

    def attempt(self, job_id, url, method, status=None, reason=None, size=0):
        with self.connect() as db:
            db.execute(
                "INSERT INTO attempts(job_id,url,method,timestamp,status,reason,bytes) VALUES(?,?,?,?,?,?,?)",
                (job_id, url, method, now(), status, reason, size),
            )

    def attempts(self, job_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM attempts WHERE job_id=?", (job_id,))]
