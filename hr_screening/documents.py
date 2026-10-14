"""Изолированное извлечение текста PDF."""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_BODY_BYTES = 6 * 1024 * 1024
MAX_PAGES = 20
MAX_TEXT_CHARS = 30000
PARSER_SLOTS = threading.BoundedSemaphore(2)


class PDFBusyError(ValueError):
    pass


class _PDFError(ValueError):
    pass


def parse_pdf(data: bytes) -> dict:
    """Возвращает текст и метаданные либо ValueError."""
    if len(data) > MAX_PDF_BYTES:
        raise ValueError('PDF превышает 5 MiB')
    if not data.startswith(b'%PDF-'):
        raise ValueError('Файл не содержит заголовок PDF')
    if not PARSER_SLOTS.acquire(blocking=False):
        raise PDFBusyError('Оба процесса разбора PDF заняты; повторите загрузку')
    try:
        try:
            result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), '--worker'], input=data, capture_output=True, timeout=8,
                                    env={'PATH': os.defpath, 'LANG': 'C.UTF-8'})
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Превышено время разбора PDF: 8 секунд') from exc
    finally:
        PARSER_SLOTS.release()
    if result.returncode:
        raise ValueError('Разбор PDF остановлен: превышен ресурс или файл поврежден')
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('PDF поврежден: не удалось извлечь текст') from exc
    if 'error' in parsed:
        raise ValueError(parsed['error'])
    return {**parsed, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'text_chars': len(parsed['text'])}


def _extract(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise _PDFError('PDF зашифрован; снимите защиту перед загрузкой')
    count = len(reader.pages)
    if not count:
        raise _PDFError('PDF не содержит страниц')
    if count > MAX_PAGES:
        raise _PDFError('В PDF больше 20 страниц')
    pages = []
    for page in reader.pages:
        raw = page.extract_text() or ''
        paragraphs = [' '.join(part.split()) for part in re.split(r'\n\s*\n', raw)]
        pages.append('\n\n'.join(part for part in paragraphs if part))
        if sum(map(len, pages)) + 2 * (len(pages) - 1) > MAX_TEXT_CHARS:
            raise _PDFError('Текст PDF превышает 30000 символов')
    text = '\n\n'.join(pages).strip()
    if len(text) < 10 or not re.search(r'\w', text):
        raise _PDFError('В PDF нет достаточного текста: пустой файл или скан; OCR не поддерживается')
    return {'text': text, 'pages': count}


def _worker():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (6, 7))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    try:
        result = _extract(sys.stdin.buffer.read(MAX_PDF_BYTES + 1))
    except _PDFError as exc:
        result = {'error': str(exc)}
    except MemoryError:
        result = {'error': 'PDF превышает лимит памяти разбора'}
    except Exception:
        result = {'error': 'PDF поврежден: не удалось извлечь текст'}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    _worker()
