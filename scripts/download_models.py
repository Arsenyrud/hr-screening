"""Загрузка закрепленных версий моделей."""

import json
from pathlib import Path

from huggingface_hub import snapshot_download


MODELS = {
    'semantic': ('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'),
    'llm': ('Qwen/Qwen3-4B-Instruct-2507', 'cdbee75f17c01a7cc42f958dc650907174af0554'),
}


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    for name, (repo, revision) in MODELS.items():
        snapshot_download(repo, revision=revision, local_dir=root / 'models' / name,
                          allow_patterns=['*.json', '*.safetensors', 'merges.txt', 'vocab.txt', 'vocab.json', 'sentencepiece.bpe.model'])
    print(json.dumps(MODELS, ensure_ascii=False, indent=2))
