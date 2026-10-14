"""Сборка записки и приложений в PDF."""

import re
import subprocess
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
FONT = Path('/usr/share/fonts/truetype/dejavu')
pdfmetrics.registerFont(TTFont('Text', str(FONT / 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('Text-Bold', str(FONT / 'DejaVuSans-Bold.ttf')))
pdfmetrics.registerFontFamily('Text', normal='Text', bold='Text-Bold', italic='Text', boldItalic='Text-Bold')
styles = getSampleStyleSheet()
styles.add(ParagraphStyle('BodyRU', fontName='Text', fontSize=9.7, leading=14.1, spaceAfter=8))
styles.add(ParagraphStyle('TitleRU', fontName='Text-Bold', fontSize=23, leading=30, spaceAfter=20))
styles.add(ParagraphStyle('HeadingRU', fontName='Text-Bold', fontSize=15, leading=20, spaceAfter=15, keepWithNext=True))
styles.add(ParagraphStyle('SmallRU', fontName='Text', fontSize=7.9, leading=10.8, spaceAfter=4))
styles.add(ParagraphStyle('CellRU', fontName='Text', fontSize=8, leading=11))


def inline(text):
    text = text.replace('\u2014', '-').replace('\u2013', '-')
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', text)
    text = escape(text).replace('`', '')
    return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)


def blocks(markdown):
    content, lines, index = [], markdown.splitlines(), 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith('|'):
            table = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                cells = [c.strip() for c in lines[index].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[:\- ]+', c) for c in cells):
                    table.append([Paragraph(inline(c), styles['CellRU']) for c in cells])
                index += 1
            if table:
                columns = len(table[0])
                width = 170 * mm
                sizes = [width / columns] * columns
                if columns == 3:
                    sizes = [width * .28, width * .36, width * .36]
                t = Table(table, colWidths=sizes, repeatRows=1, hAlign='LEFT')
                t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8edf4')),
                                       ('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#d9d9d9')),
                                       ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 7),
                                       ('RIGHTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 6),
                                       ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
                content += [t, Spacer(1, 12)]
            continue
        if line.startswith('#'):
            content.append(Paragraph(inline(line.lstrip('# ').strip()), styles['HeadingRU']))
            index += 1
            continue
        paragraph = []
        while index < len(lines) and lines[index].strip() and not lines[index].strip().startswith(('#', '|')):
            paragraph.append(lines[index].strip())
            index += 1
        content.append(Paragraph(inline(' '.join(paragraph)), styles['BodyRU']))
    return content


def page(canvas, document):
    canvas.setFont('Text', 8)
    canvas.setFillColor(colors.HexColor('#627188'))
    canvas.drawString(20 * mm, 12 * mm, 'Автоматический HR-скрининг')
    canvas.drawRightString(190 * mm, 12 * mm, str(document.page))


def build():
    (ROOT / 'assets').mkdir(exist_ok=True)
    for name in ['architecture', 'context', 'sequence', 'deployment']:
        subprocess.run(['dot', '-Tpng', '-Gdpi=180', str(ROOT / f'assets/{name}.dot'), '-o', str(ROOT / f'assets/{name}.png')], check=True)
        subprocess.run(['dot', '-Tsvg', str(ROOT / f'assets/{name}.dot'), '-o', str(ROOT / f'assets/{name}.svg')], check=True)
    story = [Spacer(1, 35 * mm), Paragraph('Автоматический HR скрининг', styles['TitleRU']),
             Paragraph('Задание 1<br/>Кадровое агентство<br/>Пояснительная записка и приложения', styles['HeadingRU']),
             Spacer(1, 15 * mm), Paragraph('Локальная обработка вакансий и резюме на AMD Radeon RX 6900 XT с ROCm. Короткий список, источники и подтверждение рекрутера.', styles['BodyRU']),
             Spacer(1, 20 * mm), Paragraph('14 октября 2026 года<br/>Версия 1.0', styles['BodyRU']), PageBreak()]
    sections = re.split(r'(?m)(?=^# )', (ROOT / 'docs/report.md').read_text())
    sections = [s for s in sections if s.strip()]
    story.append(Paragraph('Содержание', styles['HeadingRU']))
    for index, section in enumerate(sections):
        title = section.splitlines()[0].lstrip('# ')
        story.append(Paragraph(f'{inline(title)} · {index + 3}', styles['BodyRU']))
    story.append(PageBreak())
    for index, section in enumerate(sections):
        story += blocks(section)
        story.append(PageBreak())
    for section in [s for s in re.split(r'(?m)(?=^# )', (ROOT / 'docs/customer.md').read_text()) if s.strip()]:
        story += blocks(section)
        story.append(PageBreak())
    figures = [('context', 'Приложение А Контекст и доверенная граница'),
               ('deployment', 'Приложение Б Контуры целевой платформы'),
               ('architecture', 'Приложение В Модули реализации и технологии'),
               ('sequence', 'Приложение Г Выполнение одной задачи')]
    for name, title in figures:
        story.append(Paragraph(title, styles['HeadingRU']))
        picture = Image(str(ROOT / f'assets/{name}.png'))
        factor = min((170 * mm) / picture.imageWidth, (225 * mm) / picture.imageHeight)
        picture.drawWidth, picture.drawHeight = picture.imageWidth * factor, picture.imageHeight * factor
        story += [picture, PageBreak()]
    for name, title in [('measurements', 'Приложение Д Фактические измерения'), ('acceptance', 'Приложение Е Программа испытаний'), ('operations', 'Приложение Ж Эксплуатация')]:
        path = ROOT / f'docs/{name}.md'
        if path.exists():
            story.append(Paragraph(title, styles['HeadingRU']))
            story += blocks(path.read_text())
            story.append(PageBreak())
    story += [Paragraph('Источники и версии', styles['HeadingRU'])]
    for text in ['Учебное ТЗ, скан от 14 октября 2026 года, страницы 2 и 5-16',
                 'Qwen3-4B-Instruct-2507, revision cdbee75f17c01a7cc42f958dc650907174af0554',
                 'https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507',
                 'https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/raw/main/config.json',
                 'MiniLM, revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42',
                 'https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                 'Протоколы и входные данные: каталог evidence и data/demo.json в репозитории',
                 'https://github.com/Arsenyrud/hr-screening']:
        story.append(Paragraph(escape(text), styles['SmallRU']))
    output = ROOT / 'output/report.pdf'
    output.parent.mkdir(exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=(210 * mm, 297 * mm), rightMargin=20 * mm, leftMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm, title='Автоматический HR скрининг', author='Arsenyrud')
    doc.build(story, onFirstPage=page, onLaterPages=page)
    print(output)


if __name__ == '__main__':
    build()
