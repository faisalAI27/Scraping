"""Typed durable state contract; serialized values remain plain SQLite/JSON fields."""

from typing import Literal, TypedDict

JobStatus = Literal["created", "running", "completed", "partial", "cancelled"]
ResourceState = Literal["queued", "fetching", "downloaded", "extracted", "needs_review", "failed", "skipped"]
DocumentStatus = Literal["ready", "needs_review", "empty", "unsupported"]


class JobState(TypedDict):
    id: str
    seed: str
    config: str
    status: JobStatus
    created: str
    finished: str | None
    cancel: int
    termination: str | None
    warnings: str
    elapsed: float
    owner_pid: int | None
