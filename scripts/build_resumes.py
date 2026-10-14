import hashlib
import json
import re
from html import escape
from pathlib import Path

import reportlab
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'data' / 'resumes'
FONT_DIR = Path('/usr/share/fonts/truetype/dejavu')
DASHES = str.maketrans({chr(n): '-' for n in range(0x2010, 0x2016)})


def digest(value):
    return hashlib.sha256(value).hexdigest()


def clean(value):
    return str(value).translate(DASHES)


def normalized(value):
    return re.sub(r'\s+', ' ', clean(value)).strip()


class ResumeCanvas(Canvas):
    def __init__(self, *args, **kwargs):
        kwargs.update(invariant=True, pageCompression=1, lang='ru-RU')
        super().__init__(*args, **kwargs)
        self.setAuthor('HR Screening')
        self.setCreator('HR Screening')
        self.setProducer('HR Screening')


def footer(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#CCD8E3'))
    canvas.setLineWidth(.6)
    canvas.line(48, 58, A4[0] - 48, 58)
    canvas.setFillColor(colors.HexColor('#526578'))
    canvas.setFont('ResumeSans', 8)
    canvas.drawString(48, 43, 'Сведения вымышлены. Учебный тестовый набор.')
    canvas.drawRightString(A4[0] - 48, 43, f'{document.resume_id}  /  {document.page}')
    canvas.restoreState()


def build(resume):
    identifier = resume['id']
    target = OUTPUT / f'{identifier}.pdf'
    navy, blue = colors.HexColor('#16324A'), colors.HexColor('#2867A8')
    styles = {
        'tag': ParagraphStyle('tag', fontName='ResumeSans', fontSize=9, leading=14, textColor=blue, spaceAfter=18),
        'name': ParagraphStyle('name', fontName='ResumeSansBold', fontSize=25, leading=32, textColor=navy, spaceAfter=14),
        'contact': ParagraphStyle('contact', fontName='ResumeSans', fontSize=10, leading=17, textColor=colors.HexColor('#526578'), spaceAfter=20),
        'heading': ParagraphStyle('heading', fontName='ResumeSansBold', fontSize=13, leading=20, textColor=navy, spaceAfter=14),
        'body': ParagraphStyle('body', fontName='ResumeSans', fontSize=11, leading=18, textColor=navy, alignment=TA_LEFT, spaceAfter=10),
    }
    doc = SimpleDocTemplate(str(target), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=44, bottomMargin=82,
                            title=f'Синтетическое резюме {identifier}', author='HR Screening',
                            subject=f'Учебный профиль кандидата, ID {identifier}', creator='HR Screening',
                            producer='HR Screening', invariant=True, lang='ru-RU')
    doc.resume_id = identifier
    story = [Paragraph('СИНТЕТИЧЕСКОЕ РЕЗЮМЕ', styles['tag']),
             Paragraph(escape(clean(resume['name'])), styles['name']),
             Paragraph(f'ID: {escape(identifier)}<br/>Контакт: {escape(clean(resume["email"]))}', styles['contact']),
             HRFlowable(width='100%', thickness=1, color=blue), Spacer(1, 23),
             Paragraph('Профессиональный профиль.', styles['heading'])]
    for line in clean(resume['text']).splitlines():
        for part in re.split(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z])', line.strip()):
            if part:
                story.append(Paragraph(escape(part), styles['body']))
    doc.build(story, canvasmaker=ResumeCanvas, onFirstPage=footer, onLaterPages=footer)
    reader = PdfReader(target)
    extracted = '\n'.join(page.extract_text() or '' for page in reader.pages)
    for value in [resume['name'], resume['email'], identifier, resume['text']]:
        if normalized(value) not in normalized(extracted):
            raise RuntimeError(f'Неполное извлечение текста: {identifier}')
    return {'resume_id': identifier, 'filename': target.name, 'pdf_sha256': digest(target.read_bytes()),
            'text_sha256': digest(resume['text'].encode('utf-8')), 'pages': len(reader.pages)}


def main():
    if reportlab.Version != '4.4.3':
        raise RuntimeError('Установите закрепленные зависимости из requirements-report.txt')
    for name, filename in [('ResumeSans', 'DejaVuSans.ttf'), ('ResumeSansBold', 'DejaVuSans-Bold.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))
    resumes = json.loads((ROOT / 'data' / 'demo.json').read_text())['resumes']
    if {r['id'] for r in resumes} != {f'r{i:02}' for i in range(1, 33)} or len(resumes) != 32:
        raise ValueError('Ожидаются 32 синтетических профиля r01-r32')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = [build(resume) for resume in sorted(resumes, key=lambda r: r['id'])]
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Создано {len(manifest)} PDF, извлечение текста проверено')


if __name__ == '__main__':
    main()
