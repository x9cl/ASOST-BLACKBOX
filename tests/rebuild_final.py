import sys, os
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
from compose_docx import build_docx
from arabic_pdf import build_pdf

BASE = '/opt/data/projects/assost'
text = open(f'{BASE}/tests/fullbook/full_book_ar.txt.clean').read()
cover = f'{BASE}/tests/fullbook/images/p1_x35.png'
img24 = f'{BASE}/tests/goal2_images/p24_x170.png'
images = {os.path.basename(cover): cover}
if os.path.exists(img24):
    images[os.path.basename(img24)] = img24
    # insert the ch2 illustration at its natural position (start of chapter 2 area ~ 'ارتقاء المستوى')
    marker = '[IMG:p24_x170.png|full_page]'
    if 'ارتقاء المستوى' in text:
        text = text.replace('ارتقاء المستوى', f'{marker}\n\nارتقاء المستوى', 1)
pages = [{'text_with_markers': text, 'images': images}]
s1 = build_docx(pages, f'{BASE}/tests/fullbook/full_book.docx',
                book_title='Death March — المجلد الأول', cover_image=cover)
s2 = build_pdf(pages, f'{BASE}/tests/fullbook/full_book.pdf',
               book_title='Death March — المجلد الأول', cover_image=cover)
print('DOCX:', s1)
print('PDF bytes:', s2)
