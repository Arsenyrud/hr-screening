"""Проверка PDF-набора и сохранности профессиональных признаков."""

import copy
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_screening.documents import parse_pdf
from hr_screening.engine import screen


if __name__ == '__main__':
    data = json.loads((ROOT / 'data/demo.json').read_text())
    manifest = json.loads((ROOT / 'data/resumes/manifest.json').read_text())
    entries = manifest['resumes'] if isinstance(manifest, dict) else manifest
    parsed_resumes, documents = [], []
    for item in data['resumes']:
        path = ROOT / 'data/resumes' / f"{item['id']}.pdf"
        started = time.perf_counter()
        extracted = parse_pdf(path.read_bytes())
        record = next(entry for entry in entries if entry['resume_id'] == item['id'])
        documents.append({'resume_id': item['id'], 'filename': path.name, 'seconds': time.perf_counter() - started,
                          'pages': extracted['pages'], 'text_chars': extracted['text_chars'], 'sha256': extracted['sha256'],
                          'manifest_matches': extracted['sha256'] == record['pdf_sha256']})
        parsed_resumes.append({**copy.deepcopy(item), 'text': extracted['text']})
    comparisons = []
    for vacancy in data['vacancies']:
        original = screen(vacancy, data['resumes'])
        extracted = screen(vacancy, parsed_resumes)
        features = lambda result: {c['candidate_id']: {key: c[key] for key in ['score', 'matched_skills', 'missing_skills', 'experience_years']} for c in result['candidates']}
        source_by_id = {item['id']: item['text'] for item in parsed_resumes}
        comparisons.append({'vacancy_id': vacancy['id'], 'candidate_ids': [c['candidate_id'] for c in extracted['candidates']],
                            'professional_features_unchanged': features(original) == features(extracted),
                            'quotes_in_extracted_text': all(e['quote'] in source_by_id[c['candidate_id']] for c in extracted['candidates'] for e in c['evidence'])})
    result = {'format': 'text-layer PDF', 'parser': 'pypdf 5.6.0, isolated subprocess',
              'dataset_sha256': hashlib.sha256((ROOT / 'data/demo.json').read_bytes()).hexdigest(),
              'documents': documents, 'comparisons': comparisons,
              'all_valid': all(item['manifest_matches'] for item in documents) and all(item['professional_features_unchanged'] and item['quotes_in_extracted_text'] for item in comparisons),
              'limitations': ['Synthetic PDFs generated from the same fixtures', 'No OCR or independent recruitment quality claim']}
    (ROOT / 'evidence/experiment_pdf.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'documents': len(documents), 'vacancies': len(comparisons), 'all_valid': result['all_valid']}, ensure_ascii=False))
    if not result['all_valid']:
        raise SystemExit(1)
