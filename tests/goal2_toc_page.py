"""يضيف صفحة فهرس محتويات بعد صفحة العنوان في PDF وDOCX."""
import sys, os
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
from compose_docx import build_docx
import arabic_pdf
from arabic_pdf import build_pdf

BASE = '/opt/data/projects/assost'
text = open(f'{BASE}/tests/fullbook/full_book_ar.txt.clean').read()
cover = f'{BASE}/tests/fullbook/images/p1_x35.png'
img24 = f'{BASE}/tests/goal2_images/p24_x170.png'
images = {os.path.basename(cover): cover}
if os.path.exists(img24):
    images[os.path.basename(img24)] = img24

toc_entries = [
    'التمهيد: مسيرة الموت نحو الكارثة',
    'ارتقاء المستوى',
]
toc_block = 'فهرس المحتويات\n\n' + '\n\n'.join(
    f'{i+1}. «{t}»' for i, t in enumerate(toc_entries))

idx = text.find('ارتقاء المستوى')
part1 = text[:idx].strip()
part2 = text[idx:].strip() if idx > 0 else ''
part2 = part2.replace('ارتقاء المستوى', '[IMG:p24_x170.png|full_page]', 1)

pages = [{'text_with_markers': toc_block, 'images': {}}]
if part1:
    pages.append({'text_with_markers': f'«التمهيد: مسيرة الموت نحو الكارثة»\n\n{part1}', 'images': images})
if part2:
    pages.append({'text_with_markers': f'«ارتقاء المستوى»\n\n{part2}', 'images': images})

s1 = build_docx(pages, f'{BASE}/tests/fullbook/full_book.docx',
                book_title='Death March — المجلد الأول', cover_image=cover)
size = build_pdf(pages, f'{BASE}/tests/fullbook/full_book.pdf',
                 book_title='Death March — المجلد الأول', cover_image=cover)
print('DOCX:', s1)
print('PDF:', size)

import fitz
d = fitz.open(f'{BASE}/tests/fullbook/full_book.pdf')
for i, p in enumerate(d):
    if 'فهرس المحتويات' in p.get_text():
        print('TOC page at:', i + 1)
        break
print('total pages:', len(d))
