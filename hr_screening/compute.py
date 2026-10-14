"""Сопоставление в отдельном процессе."""

import os
import time
from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing import get_context


def execute(vacancy: dict, resumes: list[dict], model_path=None, llm_path=None, timeout=180, deadline=None, cancel_event=None) -> dict:
    if cancel_event is not None and cancel_event.is_set():
        raise TimeoutError('cancelled')
    if deadline and time.time() > deadline:
        raise TimeoutError('quota: срок задания истек в очереди')
    from .engine import screen

    result = screen(vacancy, resumes, model_path=model_path)
    if llm_path:
        if cancel_event is not None and cancel_event.is_set():
            raise TimeoutError('cancelled')
        from .llm import get_llm

        budget = min(45, timeout, deadline - time.time() if deadline else timeout)
        result = get_llm(llm_path).enrich(result, cancel=cancel_event.is_set if cancel_event is not None else None, timeout=max(.01, budget))
    result["compute"] = {"pid": os.getpid()}
    return result


class ComputePool:
    def __init__(self, workers=1):
        context = get_context("spawn")
        self.executor = ProcessPoolExecutor(max_workers=workers, mp_context=context)
        self.manager = context.Manager()
        self.closed = False

    def submit(self, vacancy: dict, resumes: list[dict], model_path=None, llm_path=None, timeout=180) -> Future:
        if self.closed:
            raise RuntimeError('Пул вычислений закрыт')
        event = self.manager.Event()
        future = self.executor.submit(execute, vacancy, resumes, model_path, llm_path, timeout, time.time() + timeout, event)
        future.cancel_event = event
        return future

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.executor.shutdown(wait=True, cancel_futures=True)
        finally:
            self.manager.shutdown()
