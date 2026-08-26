"""goal2_final_compose.py — التركيب النهائي بالصور الموضوعة سياقياً
يستخدم full_book_ar_with_imgs.txt (النص مع علامات الصور بمواضعها الدلالية)"""
import sys, os
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
from compose_docx import build_docx
from arabic_pdf import build_pdf

BASE = '/opt/data/projects/assost'
IMG = f'{BASE}/tests/goal2_images'

text = open(f'{BASE}/tests/fullbook/full_book_ar_with_imgs.txt').read()

cover = f'{IMG}/p1_x35.png'
images = {}
for f in os.listdir(IMG):
    images[f] = os.path.join(IMG, f)
# أضف صور الغلاف من fullbook/images إن وجدت
FI = f'{BASE}/tests/fullbook/images'
if os.path.isdir(FI):
    for f in os.listdir(FI):
        images[f] = os.path.join(FI, f)

pages = [{'text_with_markers': text, 'images': images}]
s1 = build_docx(pages, f'{BASE}/tests/fullbook/full_book.docx',
                book_title='Death March — المجلد الأول', cover_image=cover)
size = build_pdf(pages, f'{BASE}/tests/fullbook/full_book.pdf',
                 book_title='Death March — المجلد الأول', cover_image=cover)
print('DOCX:', s1)
print('PDF:', size)

import fitz
d = fitz.open(f'{BASE}/tests/fullbook/full_book.pdf')
print('pages:', len(d))
# تحقق: موضع رسمة ص24 — اطبع السياق حولها
for i, p in enumerate(d):
    if p.get_image_info() and i > 15:
        prev_t = d[i-1].get_text().strip()[-90:]
        next_t = d[i+1].get_text().strip()[:90]
        print(f'ill24 on p{i+1}')
        print('prev ends:', repr(prev_t))
        print('next starts:', repr(next_t))
        break
