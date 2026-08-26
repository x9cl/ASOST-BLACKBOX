"""goal2_fix_images.py — إصلاح عيوب الصور التي رصدها أنس:
1) صفحات الرسومات الافتتاحية (ص2-6) غائبة عن الناتج → تُدرج كاملة بترتيبها
2) رسمة ص24 وُضعت بعيداً عن نصها → تُدرج في موضعها الأصلي بالضبط:
   نهاية الفصل الأول (بعد «...إلى حدها الأقصى») وقبل بداية «ارتقاء المستوى»
"""
import sys, os
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
from compose_docx import build_docx
from arabic_pdf import build_pdf

BASE = '/opt/data/projects/assost'
IMG = f'{BASE}/tests/goal2_images'

text = open(f'{BASE}/tests/fullbook/full_book_ar.txt.clean').read()

cover = f'{IMG}/p1_x35.png'
openers = [f'{IMG}/p2_x39.png', f'{IMG}/p3_x43.png',
           f'{IMG}/p4_x47.png', f'{IMG}/p5_x51.png', f'{IMG}/p6_x55.png']
ill24 = f'{IMG}/p24_x170.png'

images = {os.path.basename(p): p for p in [cover] + openers + [ill24] if os.path.exists(p)}

# ── 1) صفحات الافتتاح: كل رسومة في صفحة مستقلة بعد الغلاف مباشرة (كالأصل) ──
pages = []
for p in openers:
    pages.append({'text_with_markers': f'[IMG:{os.path.basename(p)}|full_page]',
                  'images': images})

# ── 2) رسمة ص24 في موضعها السياقي الأصلي ──
# الأصل: ص23 تنتهي بـ«...إلى حدها الأقصى تماماً.» ثم ص24 رسمة كاملة، ثم ص25 «ارتقاء المستوى»
seam_marker = 'ارتقاء المستوى'
idx = text.find(seam_marker)
if idx < 0:
    print('ERROR: chapter 2 anchor not found')
    sys.exit(1)

part1 = text[:idx].rstrip()          # نهاية الفصل الأول (النص الذي يسبق الرسمة)
part2 = text[idx:].lstrip()          # بداية الفصل الثاني (بعد الرسمة)
# أزل التكرار: العنوان يُضاف في السطر التالي، فالنص الأصلي يبدأ به أيضاً
if part2.startswith(seam_marker):
    part2 = part2[len(seam_marker):].lstrip()

# الرسمة تذهب في نهاية part1 — تماماً كما في الكتاب الأصلي
img_mark = '[IMG:p24_x170.png|full_page]'
part1_with_img = part1 + f'\n\n{img_mark}\n\n'
# أزل أي إدراج قديم للرسمة داخل part2 إن وجد
part2_clean = part2.replace(img_mark + '\n\n', '').replace(img_mark, '')

pages.append({'text_with_markers': f'«التمهيد: مسيرة الموت نحو الكارثة»\n\n{part1_with_img}',
              'images': images})
pages.append({'text_with_markers': f'«ارتقاء المستوى»\n\n{part2_clean}',
              'images': images})

s1 = build_docx(pages, f'{BASE}/tests/fullbook/full_book.docx',
                book_title='Death March — المجلد الأول', cover_image=cover)
size = build_pdf(pages, f'{BASE}/tests/fullbook/full_book.pdf',
                 book_title='Death March — المجلد الأول', cover_image=cover)

print('DOCX:', s1)
print('PDF:', size, 'bytes')

import fitz
d = fitz.open(f'{BASE}/tests/fullbook/full_book.pdf')
print('total pages:', len(d))
# تحقق: عدد الصور المدمجة في PDF
total_imgs = sum(len(p.get_images()) for p in d)
print('embedded images in PDF:', total_imgs, '(expected: 7 openers + cover + ill24 = 9)')
