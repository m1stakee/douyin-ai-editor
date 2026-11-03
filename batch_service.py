from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Iterable
from typing import Any
import uuid
import local_logger

MAX_TRANSCRIBE_WORKERS = 5

def transcribe_worker_count(item_count: int) -> int:
    """Keep local audio conversion and ASR uploads bounded per batch."""
    return min(MAX_TRANSCRIBE_WORKERS, max(1, int(item_count)))

def run_batch(items: Iterable[Any], operation: Callable[[Any], Any], workers: int = 2, on_done: Callable[[int, Any, Any, Exception | None], None] | None = None, retries: int = 3) -> list[tuple[Any, Any, Exception | None]]:
    values = list(items)
    batch_id = uuid.uuid4().hex[:12]
    local_logger.info("batch.start batch=%s operation=%s count=%s workers=%s retries=%s", batch_id, getattr(operation,'__qualname__','operation'), len(values), workers, retries)
    def logged_operation(index, attempt):
        with local_logger.context(batch=batch_id, item=index+1, attempt=attempt+1):
            local_logger.info("batch.item.start")
            try:
                result = operation(values[index])
                local_logger.info("batch.item.ok")
                return result
            except Exception:
                local_logger.error("batch.item.failed", exc_info=True)
                raise
    results: list[tuple[Any, Any, Exception | None] | None] = [None] * len(values)
    pending = list(range(len(values)))
    for attempt in range(max(0, int(retries)) + 1):
        if not pending:
            break
        # A fresh executor is deliberately created for every retry round. Once a
        # worker reports a confirmed failure, its thread is discarded with this pool.
        round_results: dict[int, tuple[Any, Any, Exception | None]] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(pending))), thread_name_prefix=f"videoflow-{attempt + 1}") as pool:
            futures = {pool.submit(logged_operation, index, attempt): index for index in pending}
            for future in as_completed(futures):
                index = futures[future]; item = values[index]
                try: result, error = future.result(), None
                except Exception as exc: result, error = None, exc
                round_results[index] = (item, result, error)
        pending = []
        for index, value in round_results.items():
            results[index] = value
            if value[2] is not None:
                pending.append(index)
        if pending and attempt < retries:
            continue
    for index, value in enumerate(results):
        if value is not None and on_done:
            on_done(index, value[0], value[1], value[2])
    local_logger.info("batch.end batch=%s success=%s failed=%s", batch_id, sum(v is not None and v[2] is None for v in results), sum(v is not None and v[2] is not None for v in results))
    return [result for result in results if result is not None]
