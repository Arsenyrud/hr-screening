import hashlib
import io
import subprocess

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from hr_screening.documents import MAX_PDF_BYTES, parse_pdf


def make_pdf(text="Python developer. PostgreSQL and Docker. Experience: 5 years.", pages=1, encrypted=False, image=False):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=595, height=842)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            stream.set_data(('BT /F1 12 Tf 50 750 Td (' + escaped + ') Tj ET').encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
        if image:
            picture = DecodedStreamObject()
            picture.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'), NameObject('/ColorSpace'): NameObject('/DeviceRGB')})
            from pypdf.generic import NumberObject
            picture.update({NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1), NameObject('/BitsPerComponent'): NumberObject(8)})
            picture.set_data(b'\x80\x80\x80')
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im0'): writer._add_object(picture)})})
            content = DecodedStreamObject()
            content.set_data(b'q 100 0 0 100 50 700 cm /Im0 Do Q')
            page[NameObject('/Contents')] = writer._add_object(content)
    if encrypted:
        writer.encrypt('test-secret')
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def test_pdf_extracts_text_with_original_identity():
    data = make_pdf()
    parsed = parse_pdf(data)
    assert 'Python developer' in parsed['text']
    assert parsed['pages'] == 1
    assert parsed['sha256'] == hashlib.sha256(data).hexdigest()
    assert parsed['bytes'] == len(data)
    assert parsed['text_chars'] == len(parsed['text'])


@pytest.mark.parametrize('data, phrase', [(b'<html>not a PDF</html>', 'PDF'), (b'%PDF-1.7\ninvalid', 'поврежден'), (make_pdf(text=''), 'текст'), (make_pdf(text='', image=True), 'скан'), (make_pdf(pages=0), 'страниц'), (make_pdf(encrypted=True), 'зашифрован'), (make_pdf(pages=21), '20')])
def test_invalid_empty_encrypted_and_page_quota_are_explicit(data, phrase):
    with pytest.raises(ValueError, match=phrase):
        parse_pdf(data)


def test_pdf_byte_and_text_quotas_reject_before_import():
    with pytest.raises(ValueError, match='5 MiB'):
        parse_pdf(b'%PDF-' + b' ' * MAX_PDF_BYTES)
    with pytest.raises(ValueError, match='30000'):
        parse_pdf(make_pdf(text='Python ' * 5000))


def test_parser_timeout_becomes_explicit_validation_error(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('pdf-worker', 8)
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(ValueError, match='время'):
        parse_pdf(make_pdf())


def test_busy_parser_does_not_spawn_another_process(monkeypatch):
    from hr_screening import documents
    def forbidden(*args, **kwargs):
        raise AssertionError('A busy parser must not create a subprocess')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    documents.PARSER_SLOTS.acquire()
    documents.PARSER_SLOTS.acquire()
    try:
        with pytest.raises(documents.PDFBusyError, match='заняты'):
            parse_pdf(make_pdf())
    finally:
        documents.PARSER_SLOTS.release()
        documents.PARSER_SLOTS.release()
