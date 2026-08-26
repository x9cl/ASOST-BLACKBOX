"""goal2_toc.py — تحسين الهدف 2: فهرس محتويات بعناوين حقيقية + فواصل فصول في PDF
يستخدم عناوين الفصول المكتشفة من extract_pdf_with_precision."""
import sys, os, json
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import logging
logging.disable(logging.CRITICAL)
import PF
from compose_docx import build_docx
import arabic_pdf
from arabic_pdf import build_pdf

BASE = '/opt/data/projects/assost'

# 1) عناوين الفصول الحقيقية
info = PF.ProfessionalDocumentProcessor.extract_pdf_with_precision(f'{BASE}/book.pdf')
chapters = [(c.get('title', ''), c.get('start_page'), c.get('end_page'))
            for c in info['chapters']]
print('chapters:', chapters)

AR_TITLES = {
    'Prologue: Death March to Disaster': 'التمهيد: مسيرة الموت نحو الكارثة',
    'Level Up': 'ارتقاء المستوى',
}

# 2) النص النظيف
text = open(f'{BASE}/tests/fullbook/full_book_ar.txt.clean').read()
cover = f'{BASE}/tests/fullbook/images/p1_x35.png'
img24 = f'{BASE}/tests/goal2_images/p24_x170.png'

# 3) أدخل عناوين الفصول عند بداية كل فصل (بأول جملة مميزة معروفة)
anchors = [
    ('استهلال: مسيرة الموت نحو الكارثة', 0),          # بداية الكتاب
    ('ارتقاء المستوى', text.find('ارتقاء المستوى')),
]
for ar_title, pos in anchors:
    if pos > 0 and f'<H1>{ar_title}</H1>' not in text:
        pass  # العلامات تُدار عبر build_pdf التالي

# بناء صفحات للمولد: فصل الفصلين بعنوانين
idx_ch2 = text.find('ارتقاء المستوى')
part1 = text[:idx_ch2].strip()
part2 = text[idx_ch2:].strip() if idx_ch2 > 0 else ''

images = {os.path.basename(cover): cover}
if os.path.exists(img24):
    images[os.path.basename(img24)] = img24
    part2 = part2.replace('ارتقاء المستوى', '[IMG:p24_x170.png|full_page]', 1)

pages = []
if part1:
    pages.append({'text_with_markers': f'«{AR_TITLES.get(chapters[0][0], chapters[0][0])}»\n\n{part1}',
                  'images': images})
if part2:
    pages.append({'text_with_markers': f'«{AR_TITLES.get(chapters[1][0], chapters[1][0])}»\n\n{part2}',
                  'images': images})

s1 = build_docx(pages, f'{BASE}/tests/fullbook/full_book.docx',
                book_title='Death March — المجلد الأول', cover_image=cover)
size = build_pdf(pages, f'{BASE}/tests/fullbook/full_book.pdf',
                 book_title='Death March — المجلد الأول', cover_image=cover,
                 chapter_start_every=0)
print('DOCX:', s1)
print('PDF:', size, 'bytes')

import fitz
d = fitz.open(f'{BASE}/tests/fullbook/full_book.pdf')
print('pages:', len(d))
