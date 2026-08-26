"""goal2_image_context.py — الإصلاح النهائي لموضع رسمة ص24
الموضع الصحيح (كالأصل): بعد «...إلى حدها الأقصى تماماً.» وقبل «لا بد أن مستواي قد ارتفع...»
داخل الفصل الثاني — وليس نهاية الفصل الأول."""
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

# ── الموضع السياقي الدقيق للرسمة ──
anchor_before = 'إلى حدها الأقصى تماماً.'
anchor_after = 'لا بد أن مستواي قد ارتفع'
i1 = text.find(anchor_before)
i2 = text.find(anchor_after)
assert i1 > 0 and i2 > i1, f'anchors not found: {i1}, {i2}'

img_mark = '[IMG:p24_x170.png|full_page]'
mid = text[i1 + len(anchor_before):i2]  # الفراغ بينهما
text_ctx = text[:i1 + len(anchor_before)] + '\n\n' + img_mark + '\n\n' + text[i2:]

# ── بناء الصفحات ──
pages = []
for p in openers:
    pages.append({'text_with_markers': f'[IMG:{os.path.basename(p)}|full_page]',
                  'images': images})

idx = text_ctx.find('ارتقاء المستوى')
part1 = text_ctx[:idx].rstrip()
part2 = text_ctx[idx:].lstrip()
if part2.startswith('ارتقاء المستوى'):
    part2_body = part2[len('ارتقاء المستوى'):].lstrip()
else:
    part2_body = part2

pages.append({'text_with_markers': f'«التمهيد: مسيرة الموت نحو الكارثة»\n\n{part1}',
              'images': images})
pages.append({'text_with_markers': f'«ارتقاء المستوى»\n\n{part2_body}',
              'images': images})

s1 = build_docx(pages, f'{BASE}/tests/fullbook/full_book.docx',
                book_title='Death March — المجلد الأول', cover_image=cover)
size = build_pdf(pages, f'{BASE}/tests/fullbook/full_book.pdf',
                 book_title='Death March — المجلد الأول', cover_image=cover)
print('DOCX:', s1)
print('PDF:', size)

import fitz
d = fitz.open(f'{BASE}/tests/fullbook/full_book.pdf')
# تحقق سياقي: اطبع ما حول صفحة الرسمة
for i, p in enumerate(d):
    if p.get_image_info() and i > 10:
        prev_t = d[i-1].get_text().strip()[-100:]
        next_t = d[i+1].get_text().strip()[:100] if i+1 < len(d) else ''
        print(f'IMAGE on p{i+1}')
        print(f'  prev ends: ...{prev_t!r}')
        print(f'  next starts: {next_t!r}')
        break
print('total pages:', len(d))
