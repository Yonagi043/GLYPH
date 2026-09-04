"""Bounded in-process operations with cooperative cancellation and recovery."""

from __future__ import annotations

import re
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable


OperationRunner = Callable[[Callable[[str], None], dict[str, Any]], dict[str, Any]]
TERMINAL_STATUSES = {"completed", "failed", "canceled"}


class OperationError(ValueError):
    """Raised for invalid operation transitions or identifiers."""


class OperationCancelled(RuntimeError):
    """Internal cooperative cancellation signal."""


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _error_code(error: Exception) -> str:
    candidate = str(error).split(":", 1)[0]
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", candidate):
        return candidate
    return f"OPERATION_FAILED_{type(error).__name__.upper()}"


class OperationManager:
    """Run only predeclared callables; no shell or caller-provided paths."""

    def __init__(self, runners: dict[str, OperationRunner]):
        if not runners:
            raise ValueError("OPERATION_RUNNER_REQUIRED")
        self._runners = dict(runners)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._events: dict[str, threading.Event] = {}
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="glyph-workbench-operation",
        )

    def submit(self, kind: str) -> dict[str, Any]:
        if kind not in self._runners:
            raise OperationError("OPERATION_KIND_NOT_ALLOWED")
        operation_id = f"operation_{uuid.uuid4().hex[:24]}"
        now = _now()
        with self._lock:
            self._jobs[operation_id] = {
                "operation_id": operation_id,
                "kind": kind,
                "status": "queued",
                "stage": "queued",
                "attempts": 0,
                "created_at": now,
                "updated_at": now,
                "context": {},
                "result": None,
                "error_code": None,
            }
            self._events[operation_id] = threading.Event()
            self._schedule(operation_id)
            return self.get(operation_id)

    def _schedule(self, operation_id: str) -> None:
        self._futures[operation_id] = self._executor.submit(
            self._execute, operation_id
        )

    def _execute(self, operation_id: str) -> None:
        with self._lock:
            job = self._jobs[operation_id]
            job.update(
                {
                    "status": "running",
                    "stage": "starting",
                    "attempts": job["attempts"] + 1,
                    "updated_at": _now(),
                    "error_code": None,
                }
            )
        event = self._events[operation_id]

        def checkpoint(stage: str) -> None:
            with self._lock:
                job = self._jobs[operation_id]
                job["stage"] = stage
                job["updated_at"] = _now()
            if event.is_set():
                raise OperationCancelled("OPERATION_CANCELED")

        try:
            result = self._runners[job["kind"]](checkpoint, job["context"])
            checkpoint("completed")
        except OperationCancelled:
            with self._lock:
                job.update(
                    {
                        "status": "canceled",
                        "stage": "canceled",
                        "updated_at": _now(),
                        "result": None,
                        "error_code": "OPERATION_CANCELED",
                    }
                )
        except Exception as error:
            with self._lock:
                job.update(
                    {
                        "status": "failed",
                        "stage": "failed",
                        "updated_at": _now(),
                        "result": None,
                        "error_code": _error_code(error),
                    }
                )
        else:
            with self._lock:
                job.update(
                    {
                        "status": "completed",
                        "stage": "completed",
                        "updated_at": _now(),
                        "result": result,
                        "error_code": None,
                    }
                )

    def get(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            if operation_id not in self._jobs:
                raise KeyError(operation_id)
            job = self._jobs[operation_id]
            return {
                key: job[key]
                for key in (
                    "operation_id",
                    "kind",
                    "status",
                    "stage",
                    "attempts",
                    "created_at",
                    "updated_at",
                    "result",
                    "error_code",
                )
            }

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            identifiers = sorted(
                self._jobs,
                key=lambda identifier: self._jobs[identifier]["created_at"],
                reverse=True,
            )
        return [self.get(identifier) for identifier in identifiers]

    def cancel(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            if operation_id not in self._jobs:
                raise KeyError(operation_id)
            job = self._jobs[operation_id]
            if job["status"] in TERMINAL_STATUSES:
                raise OperationError("OPERATION_ALREADY_TERMINAL")
            self._events[operation_id].set()
            future = self._futures[operation_id]
            if future.cancel():
                job.update(
                    {
                        "status": "canceled",
                        "stage": "canceled_before_start",
                        "updated_at": _now(),
                        "error_code": "OPERATION_CANCELED",
                    }
                )
            else:
                job.update(
                    {
                        "status": "cancel_requested",
                        "updated_at": _now(),
                    }
                )
        return self.get(operation_id)

    def resume(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            if operation_id not in self._jobs:
                raise KeyError(operation_id)
            job = self._jobs[operation_id]
            if job["status"] not in {"canceled", "failed"}:
                raise OperationError("OPERATION_NOT_RECOVERABLE")
            self._events[operation_id] = threading.Event()
            job.update(
                {
                    "status": "queued",
                    "stage": "recovery_queued",
                    "updated_at": _now(),
                    "result": None,
                    "error_code": None,
                }
            )
            self._schedule(operation_id)
        return self.get(operation_id)

    def wait(self, operation_id: str, timeout: float = 30) -> dict[str, Any]:
        self._futures[operation_id].result(timeout=timeout)
        return self.get(operation_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)