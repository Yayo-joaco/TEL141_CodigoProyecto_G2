# ==============================================================
# Task Queue - Async execution engine (R1.4, R1.6, R1.7)
#
# Decouples API request acceptance from heavy execution:
#   - API enqueues a task and returns a ticket_id immediately
#   - Dedicated worker thread processes tasks from the queue
#   - Clients poll /api/task/<ticket_id> for status/result
#
# This architecture allows the worker to run on a separate machine
# (e.g., consuming from RabbitMQ) without changing the API interface,
# satisfying R1.7 (módulos en máquinas distintas).
# ==============================================================

import logging
import queue
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("orchestrator.queue")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    def __init__(self, ticket_id: str, name: str,
                 fn: Callable, args: tuple, kwargs: dict):
        self.ticket_id = ticket_id
        self.name = name
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.status = TaskStatus.PENDING
        self.result: Optional[Any] = None
        self.error: Optional[str] = None
        self.created_at = datetime.utcnow().isoformat()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "name": self.name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class TaskQueue:
    """
    In-process task queue with a dedicated worker thread (R1.4, R1.6, R1.7).

    - API layer enqueues tasks and returns a ticket_id immediately (non-blocking)
    - Single worker thread processes tasks sequentially, preventing overcommit
    - Results stored in memory; clients poll /api/task/<ticket_id>

    The worker is interchangeable with a remote consumer (RabbitMQ, Redis Queue)
    without changing the Orchestrator interface — satisfying R1.7.
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="task-queue-worker"
        )
        self._worker.start()
        logger.info("TaskQueue worker started (thread: %s)", self._worker.name)

    def enqueue(self, name: str, fn: Callable, *args, **kwargs) -> str:
        """Enqueue a callable and return a ticket_id immediately."""
        ticket_id = str(uuid.uuid4())[:12]
        task = Task(ticket_id=ticket_id, name=name, fn=fn,
                    args=args, kwargs=kwargs)
        with self._lock:
            self._tasks[ticket_id] = task
        self._queue.put(task)
        logger.info("Enqueued task '%s' (ticket=%s, queue_size=%d)",
                    name, ticket_id, self._queue.qsize())
        return ticket_id

    def get_task(self, ticket_id: str) -> Optional[dict]:
        """Return task status dict, or None if ticket not found."""
        with self._lock:
            task = self._tasks.get(ticket_id)
        return task.to_dict() if task else None

    def queue_size(self) -> int:
        return self._queue.qsize()

    def _run(self):
        """Worker loop — runs in a dedicated daemon thread."""
        while True:
            task: Task = self._queue.get()
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow().isoformat()
            logger.info("Task started: '%s' (ticket=%s)", task.name, task.ticket_id)
            try:
                result = task.fn(*task.args, **task.kwargs)
                task.result = result
                task.status = TaskStatus.COMPLETED
                logger.info("Task completed: '%s' (ticket=%s)",
                            task.name, task.ticket_id)
            except Exception as e:
                task.error = str(e)
                task.status = TaskStatus.FAILED
                logger.error("Task failed: '%s' (ticket=%s): %s",
                             task.name, task.ticket_id, e)
            finally:
                task.finished_at = datetime.utcnow().isoformat()
                self._queue.task_done()
