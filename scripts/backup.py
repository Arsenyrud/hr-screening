"""Резервная копия SQLite без остановки сервиса."""

import argparse
import hashlib
from pathlib import Path
import sqlite3


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('target')
    args = parser.parse_args()
    target = Path(args.target)
    if target.exists():
        raise SystemExit('Файл назначения уже существует')
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.source) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
        result = destination.execute('PRAGMA integrity_check').fetchone()[0]
    if result != 'ok':
        raise SystemExit(result)
    print(hashlib.sha256(target.read_bytes()).hexdigest(), target.name)
