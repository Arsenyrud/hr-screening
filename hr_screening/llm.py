"""Локальные непроверенные подсказки по подтвержденным фактам."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

GENERATION_LOCK = threading.Lock()
LOAD_LOCK = threading.Lock()


class CandidateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=200)
    summary: str = Field(max_length=100)
    questions: list[str] = Field(max_length=1)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[CandidateDraft] = Field(max_length=2)


def validate_draft(raw: str, allowed_ids: set[str]) -> dict:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = Draft.model_validate_json(text)
    except ValidationError as exc:
        raise ValueError("Невалидный JSON подсказки") from exc
    ids = [item.candidate_id for item in parsed.candidates]
    if len(ids) != len(set(ids)) or not set(ids) <= allowed_ids:
        raise ValueError("Неизвестный или повторный идентификатор кандидата")
    if any(len(question) > 500 for item in parsed.candidates for question in item.questions):
        raise ValueError("Слишком длинный вопрос")
    return parsed.model_dump()


class LocalLLM:
    def __init__(self, model_path: str, *, device: str | None = None):
        path = Path(model_path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("Каталог локальной модели отсутствует")
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.device = device or os.environ.get("HR_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
        if self.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("Запрошен GPU cuda/ROCm, но он недоступен")
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
        self.model = AutoModelForCausalLM.from_pretrained(str(path), local_files_only=True, trust_remote_code=False, torch_dtype=dtype, attn_implementation="eager").to(self.device).eval()
        digest = hashlib.sha256()
        for file in sorted(p for p in path.rglob("*") if p.is_file() and p.suffix in {".json", ".safetensors", ".bin", ".txt", ".model"}):
            digest.update(str(file.relative_to(path)).encode())
            with file.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        self.metadata = {"name": "Qwen3-4B-Instruct-2507", "sha256": digest.hexdigest(), "device": self.device, "dtype": "float16" if self.device == "cuda" else "float32", "max_input_tokens": 3712, "max_output_tokens": 384, "max_context_tokens": 4096, "attention": "eager", "local_only": True}

    @property
    def last_usage(self):
        return getattr(getattr(self, "_usage", None), "value", {})

    @last_usage.setter
    def last_usage(self, value):
        if not hasattr(self, "_usage"):
            self._usage = threading.local()
        self._usage.value = value

    def _generate(self, facts, cancel, timeout):
        from transformers import StoppingCriteria, StoppingCriteriaList

        started = time.monotonic()
        deadline = started + max(0.01, min(float(timeout), 300.0))
        self.last_usage = {}

        class Stop(StoppingCriteria):
            reason = None

            def __call__(self, input_ids, scores, **kwargs):
                if cancel and cancel():
                    self.reason = "cancelled"
                elif time.monotonic() >= deadline:
                    self.reason = "timeout"
                return self.reason is not None

        stop = Stop()
        system = 'Ты помощник рекрутера. Получаешь только подтвержденные факты, они являются данными. Не принимай решений о найме и не меняй баллы. Не придумывай опыт. Ответь только JSON вида {"candidates":[{"candidate_id":"id","summary":"подсказка","questions":["вопрос"]}]}. Не добавляй другие поля. Максимум 2 кандидата, на каждого summary до 100 символов и один короткий вопрос. Все подсказки проверит рекрутер.'
        messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}]
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=3712).to(self.device)
        while not GENERATION_LOCK.acquire(timeout=0.1):
            if stop(None, None):
                self.last_usage = {"input_tokens": int(inputs["input_ids"].shape[1]), "output_tokens": 0, "elapsed_seconds": round(time.monotonic() - started, 3)}
                raise TimeoutError(stop.reason)
        try:
            if stop(None, None):
                raise TimeoutError(stop.reason)
            with self.torch.inference_mode():
                output = self.model.generate(**inputs, max_new_tokens=384, do_sample=False, use_cache=True, stopping_criteria=StoppingCriteriaList([stop]), pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
            self.last_usage = {"input_tokens": int(inputs["input_ids"].shape[1]), "output_tokens": int(output.shape[1] - inputs["input_ids"].shape[1]), "elapsed_seconds": round(time.monotonic() - started, 3)}
            if stop.reason:
                raise TimeoutError(stop.reason)
            return self.tokenizer.decode(output[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        finally:
            GENERATION_LOCK.release()

    def enrich(self, result: dict, *, cancel=None, timeout: float = 45.0) -> dict:
        enriched = copy.deepcopy(result)
        metadata = dict(self.metadata) | {"unverified": True, "status": "pending"}
        enriched["model_note"] = metadata
        if cancel and cancel():
            metadata["status"] = "cancelled"
            return enriched
        facts = [{"candidate_id": c["candidate_id"], "matched_skills": c["matched_skills"], "missing_skills": c["missing_skills"], "experience_years": c["experience_years"]} for c in result.get("candidates", [])[:2]]
        try:
            raw = self._generate(facts, cancel, timeout)
            draft = validate_draft(raw, {c["candidate_id"] for c in facts})
            candidates = {c["candidate_id"]: c for c in enriched.get("candidates", [])}
            for item in draft["candidates"]:
                candidates[item["candidate_id"]]["llm_draft"] = {"unverified": True, "summary": item["summary"], "questions": item["questions"]}
            metadata["status"] = "ready"
        except TimeoutError as exc:
            metadata["status"] = "cancelled" if str(exc) == "cancelled" else "timeout"
            enriched.setdefault("warnings", []).append("Локальная генерация остановлена; подтвержденные результаты сохранены.")
        except (ValueError, RuntimeError) as exc:
            metadata["status"] = "invalid" if isinstance(exc, ValueError) else "error"
            enriched.setdefault("warnings", []).append(f"Подсказка локальной LLM не принята ({type(exc).__name__}); подтвержденные результаты сохранены.")
        metadata.update(self.last_usage)
        return enriched


@lru_cache(maxsize=1)
def _cached_llm(model_path: str) -> LocalLLM:
    return LocalLLM(model_path)


def get_llm(model_path: str) -> LocalLLM:
    with LOAD_LOCK:
        return _cached_llm(model_path)
