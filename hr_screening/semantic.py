"""Локальные эмбеддинги с ограничением длины."""
from __future__ import annotations

import hashlib
import os
import threading
from functools import lru_cache
from pathlib import Path

MAX_TOKENS = 128
MAX_CHUNKS = 32
BATCH_SIZE = 16
MAX_TEXT_CHARS = 100_000
INFERENCE_LOCK = threading.Lock()
LOAD_LOCK = threading.Lock()


class LocalSemanticEncoder:
    def __init__(self, model_path: str):
        path = Path(model_path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("Каталог локальной модели отсутствует")
        from transformers import AutoModel, AutoTokenizer
        import torch

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
        device = os.environ.get("HR_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("Запрошен GPU cuda/ROCm, но он недоступен")
        self.device = device
        self.model = AutoModel.from_pretrained(str(path), local_files_only=True, trust_remote_code=False, torch_dtype=torch.float16 if device == "cuda" else torch.float32, attn_implementation="eager").to(device).eval()
        digest = hashlib.sha256()
        files = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix in {".json", ".safetensors", ".bin", ".txt", ".model"})
        for file in files:
            digest.update(str(file.relative_to(path)).encode())
            with file.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        self.metadata = {"mode": "semantic", "name": "paraphrase-multilingual-MiniLM-L12-v2", "device": device, "dtype": "float16" if device == "cuda" else "float32", "sha256": digest.hexdigest(), "max_tokens": MAX_TOKENS, "max_chunks": MAX_CHUNKS, "pooling": "attention-mask mean", "aggregation": "0.5 mean chunk cosine + 0.5 max chunk cosine"}

    def _chunks(self, text: str):
        content_size = MAX_TOKENS - self.tokenizer.num_special_tokens_to_add(pair=False)
        ids = self.tokenizer(text[:MAX_TEXT_CHARS], add_special_tokens=False, truncation=True, max_length=content_size * MAX_CHUNKS + 1)["input_ids"]
        truncated = len(text) > MAX_TEXT_CHARS or len(ids) > content_size * MAX_CHUNKS
        ids = ids[:content_size * MAX_CHUNKS]
        chunks = [self.tokenizer.prepare_for_model(ids[i:i + content_size], add_special_tokens=True, truncation=True, max_length=MAX_TOKENS, return_attention_mask=True) for i in range(0, len(ids), content_size)]
        if not chunks:
            chunks = [self.tokenizer.prepare_for_model([], add_special_tokens=True, return_attention_mask=True)]
        return chunks, truncated

    def _encode(self, chunks):
        torch = self.torch
        result = []
        for offset in range(0, len(chunks), BATCH_SIZE):
            batch = self.tokenizer.pad(chunks[offset:offset + BATCH_SIZE], padding=True, return_tensors="pt").to(self.device)
            with torch.inference_mode():
                states = self.model(**batch).last_hidden_state
                mask = batch["attention_mask"].unsqueeze(-1).to(states.dtype)
                pooled = (states * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                result.append(torch.nn.functional.normalize(pooled, p=2, dim=1))
        return torch.cat(result)

    def compare(self, query: str, documents: list[str]):
        with INFERENCE_LOCK:
            return self._compare(query, documents)

    def _compare(self, query, documents):
        if not query.strip() or not any(document.strip() for document in documents):
            return [0.0] * len(documents), {"query_truncated": False, "truncated_documents": []}
        torch = self.torch
        query_chunks, query_truncated = self._chunks(query)
        query_vector = self._encode(query_chunks).mean(dim=0)
        query_vector = torch.nn.functional.normalize(query_vector, p=2, dim=0)
        scores, truncated = [], []
        for index, document in enumerate(documents):
            if not document.strip():
                scores.append(0.0)
                continue
            chunks, clipped = self._chunks(document)
            cosine = self._encode(chunks) @ query_vector
            similarity = 0.5 * cosine.mean() + 0.5 * cosine.max()
            scores.append(round(float(similarity.clamp(0, 1).item()), 6))
            if clipped:
                truncated.append(index)
        return scores, {"query_truncated": query_truncated, "truncated_documents": truncated}


@lru_cache(maxsize=2)
def _cached_encoder(model_path: str) -> LocalSemanticEncoder:
    """Кэш двух локальных моделей."""
    return LocalSemanticEncoder(model_path)


def get_encoder(model_path: str) -> LocalSemanticEncoder:
    with LOAD_LOCK:
        return _cached_encoder(model_path)
