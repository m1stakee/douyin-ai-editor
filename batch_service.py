from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Iterable
from typing import Any

def run_batch(items: Iterable[Any], operation: Callable[[Any], Any], workers: int = 2, on_done: Callable[[int, Any, Any, Exception | None], None] | None = None) -> list[tuple[Any, Any, Exception | None]]:
    values = list(items)
    results: list[tuple[Any, Any, Exception | None] | None] = [None] * len(values)
    with ThreadPoolExecutor(max_workers=max(1, int(workers)), thread_name_prefix="videoflow") as pool:
        futures = {pool.submit(operation, item): (index, item) for index, item in enumerate(values)}
        for future in as_completed(futures):
            index, item = futures[future]
            try: result, error = future.result(), None
            except Exception as exc: result, error = None, exc
            results[index] = (item, result, error)
            if on_done: on_done(index, item, result, error)
    return [result for result in results if result is not None]
