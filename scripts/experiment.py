"""Воспроизводимое сравнение режимов на синтетических данных."""

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_screening.engine import screen


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int((len(values) - 1) * fraction))]


def hardware():
    import torch
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), platform.processor())
    ram = next((int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')), 0)
    return {'os': platform.system(), 'kernel': platform.release(), 'cpu': cpu, 'cpu_count': os.cpu_count(), 'ram_bytes': ram, 'python': platform.python_version(),
            'torch': torch.__version__, 'rocm': torch.version.hip, 'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            'vram_bytes': torch.cuda.get_device_properties(0).total_memory if torch.cuda.is_available() else 0}


def run(mode, repeats):
    data = json.loads((ROOT / 'data/demo.json').read_text())
    model_path = str(ROOT / 'models/semantic') if mode == 'semantic' else None
    timings, evaluations, sample = [], [], None
    started = time.perf_counter()
    screen(data['vacancies'][0], data['resumes'], model_path=model_path)
    cold = time.perf_counter() - started
    for vacancy in data['vacancies']:
        relevant = set(data['labels'][vacancy['id']])
        for _ in range(repeats):
            started = time.perf_counter()
            result = screen(vacancy, data['resumes'], model_path=model_path)
            timings.append(time.perf_counter() - started)
        selected = [c['candidate_id'] for c in result['candidates']]
        hits = len(set(selected) & relevant)
        evaluations.append({'vacancy_id': vacancy['id'], 'selected': selected, 'relevant': sorted(relevant),
                            'precision_at_k': hits / len(selected) if selected else 0, 'recall_at_k': hits / len(relevant) if relevant else 0,
                            'model': {k: v for k, v in result['model'].items() if k != 'path'}})
        if vacancy['id'] == 'v-python':
            sample = result
    out = {'mode': mode, 'repeats_per_vacancy': repeats, 'dataset_sha256': hashlib.sha256((ROOT / 'data/demo.json').read_bytes()).hexdigest(),
           'resumes': len(data['resumes']), 'vacancies': len(data['vacancies']), 'hardware': hardware(), 'cold_seconds': cold,
           'warm_seconds': timings, 'p50_seconds': statistics.median(timings), 'p95_seconds': percentile(timings, .95),
           'p99_seconds': percentile(timings, .99), 'evaluations': evaluations,
           'limitations': ['Synthetic hand-authored labels, not an independent hiring quality study', 'No ATS integration or production SLA inferred']}
    (ROOT / 'evidence').mkdir(exist_ok=True)
    (ROOT / 'evidence' / f'experiment_{mode}.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    if sample:
        sample['model'].pop('path', None)
        (ROOT / 'evidence' / f'shortlist_{mode}.json').write_text(json.dumps(sample, ensure_ascii=False, indent=2))
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['baseline', 'semantic'], default='baseline')
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('repeats must be positive')
    result = run(args.mode, args.repeats)
    print(json.dumps({k: result[k] for k in ['mode', 'p50_seconds', 'p95_seconds', 'cold_seconds']}, ensure_ascii=False, indent=2))
