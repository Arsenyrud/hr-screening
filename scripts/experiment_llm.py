"""Локальная генерация на GPU с протоколом ресурсов."""

import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_screening.engine import screen
from hr_screening.llm import LocalLLM


if __name__ == '__main__':
    import torch
    if not torch.cuda.is_available():
        raise SystemExit('Для этого протокола требуется ROCm/GPU')
    torch.cuda.reset_peak_memory_stats()
    data = json.loads((ROOT / 'data/demo.json').read_text())
    vacancy = next(v for v in data['vacancies'] if v['id'] == 'v-python')
    result = screen(vacancy, data['resumes'])
    before = copy.deepcopy(result)
    started = time.perf_counter()
    llm = LocalLLM(str(ROOT / 'models/llm'), device='cuda')
    load_seconds = time.perf_counter() - started
    trials = []
    for _ in range(2):
        started = time.perf_counter()
        enriched = llm.enrich(result, timeout=45)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        note = enriched['model_note']
        trials.append({'elapsed_seconds': elapsed, 'model_note': note,
                       'drafts': [{'candidate_id': c['candidate_id'], **c['llm_draft']} for c in enriched['candidates'] if 'llm_draft' in c],
                       'scores_unchanged': [c['score'] for c in enriched['candidates']] == [c['score'] for c in before['candidates']],
                       'evidence_unchanged': [c['evidence'] for c in enriched['candidates']] == [c['evidence'] for c in before['candidates']]})
    manifest = []
    for path in sorted((ROOT / 'models/llm').glob('*.safetensors')):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
        manifest.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
    output = {'gpu': torch.cuda.get_device_name(0), 'vram_bytes': torch.cuda.get_device_properties(0).total_memory,
              'torch': torch.__version__, 'rocm': torch.version.hip, 'load_seconds': load_seconds,
              'peak_allocated_bytes': torch.cuda.max_memory_allocated(), 'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
              'model_revision': 'cdbee75f17c01a7cc42f958dc650907174af0554', 'weights': manifest, 'trials': trials,
              'all_valid': all(t['model_note']['status'] == 'ready' and t['scores_unchanged'] and t['evidence_unchanged'] for t in trials),
              'limitations': ['Two synthetic prompts', 'JSON validity does not prove factual correctness', 'One GPU generation sequence']}
    (ROOT / 'evidence').mkdir(exist_ok=True)
    (ROOT / 'evidence/experiment_llm.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2))
