"""
Менеджер фоновых задач парсинга.
Хранит in-memory состояние задач и шлёт события прогресса через asyncio.Queue
(по одной очереди на каждого подписчика — обычно это SSE-стрим фронта).
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger

from ..models.schemas import (
    Organization,
    SearchRequest,
    TaskProgress,
    TaskResult,
    TaskStage,
)


@dataclass
class _TaskState:
    request: SearchRequest
    progress: TaskProgress
    organizations: list[Organization] = field(default_factory=list)
    # Очередь событий для SSE-подписчиков
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    # asyncio.Task, на котором крутится парсинг
    worker: Optional[asyncio.Task] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class TaskManager:
    """In-memory стор задач. На старте хватает, горизонтальное масштабирование — потом."""

    def __init__(self) -> None:
        self._tasks: dict[str, _TaskState] = {}
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- API

    async def create(self, request: SearchRequest) -> str:
        """Создать задачу, вернуть task_id."""
        task_id = uuid.uuid4().hex[:12]
        now = datetime.utcnow()
        state = _TaskState(
            request=request,
            progress=TaskProgress(
                task_id=task_id,
                stage=TaskStage.QUEUED,
                started_at=now,
                updated_at=now,
            ),
        )
        async with self._lock:
            self._tasks[task_id] = state
        return task_id

    async def start(self, task_id: str, runner_coro) -> None:
        """Запустить runner в фоне и прибрать за собой по завершении."""
        state = self._get(task_id)
        state.worker = asyncio.create_task(
            self._runner(task_id, runner_coro), name=f"task-{task_id}"
        )

    async def _runner(self, task_id: str, runner_coro) -> None:
        state = self._get(task_id)
        try:
            await runner_coro
        except asyncio.CancelledError:
            await self._set_stage(task_id, TaskStage.CANCELLED, "Отменено")
        except Exception as e:  # noqa: BLE001
            logger.exception("task {} failed: {}", task_id, e)
            await self._set_stage(task_id, TaskStage.FAILED,
                                  f"Ошибка: {e}", error=str(e))
        else:
            await self._set_stage(task_id, TaskStage.DONE, "Готово")

    async def cancel(self, task_id: str) -> bool:
        state = self._get(task_id)
        if state is None or state.worker is None:
            return False
        state.cancel_event.set()
        state.worker.cancel()
        return True

    def get_progress(self, task_id: str) -> Optional[TaskProgress]:
        s = self._tasks.get(task_id)
        return s.progress if s else None

    def get_result(self, task_id: str) -> Optional[TaskResult]:
        s = self._tasks.get(task_id)
        if s is None:
            return None
        return TaskResult(
            task_id=task_id,
            progress=s.progress,
            organizations=s.organizations,
            search=s.request,
        )

    def list_all(self) -> list[TaskProgress]:
        return [s.progress for s in self._tasks.values()]

    async def subscribe(self, task_id: str) -> "asyncio.Queue":
        """Вернуть очередь событий прогресса (для SSE-стрима)."""
        state = self._get(task_id)
        # Создаём новую очередь, чтобы несколько подписчиков не воровали
        # события друг у друга.
        q: asyncio.Queue = asyncio.Queue()
        # Если задача уже идёт — сразу толкаем текущее состояние
        await q.put(state.progress.model_copy())
        # Регистрируем очередь в состоянии
        state.__dict__["_subs"] = state.__dict__.get("_subs", []) + [q]
        return q

    def unsubscribe(self, task_id: str, queue: "asyncio.Queue") -> None:
        state = self._tasks.get(task_id)
        if state and "_subs" in state.__dict__:
            try:
                state.__dict__["_subs"].remove(queue)
            except ValueError:
                pass

    async def update_progress(
        self,
        task_id: str,
        *,
        stage: Optional[TaskStage] = None,
        processed: Optional[int] = None,
        total: Optional[int] = None,
        found_with_website: Optional[int] = None,
        found_without_website: Optional[int] = None,
        message: str = "",
    ) -> None:
        state = self._get(task_id)
        p = state.progress
        if stage is not None:
            p.stage = stage
        if processed is not None:
            p.processed = processed
        if total is not None:
            p.total = total
        if found_with_website is not None:
            p.found_with_website = found_with_website
        if found_without_website is not None:
            p.found_without_website = found_without_website
        if message:
            p.message = message
        p.updated_at = datetime.utcnow()

        # Разослать событие всем подписчикам
        snap = p.model_copy()
        for q in state.__dict__.get("_subs", []):
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                pass

    async def set_organizations(self, task_id: str, orgs: list[Organization]) -> None:
        state = self._get(task_id)
        state.organizations = orgs

    # ------------------------------------------------------------ helpers
    def _get(self, task_id: str) -> _TaskState:
        s = self._tasks.get(task_id)
        if s is None:
            raise KeyError(f"task {task_id} not found")
        return s

    async def _set_stage(
        self, task_id: str, stage: TaskStage, message: str,
        error: Optional[str] = None,
    ) -> None:
        state = self._get(task_id)
        state.progress.stage = stage
        state.progress.message = message
        state.progress.error = error
        state.progress.updated_at = datetime.utcnow()
        snap = state.progress.model_copy()
        for q in state.__dict__.get("_subs", []):
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                pass


# Синглтон-менеджер на всё приложение
task_manager = TaskManager()
