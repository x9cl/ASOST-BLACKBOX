import sys, os
sys.path.insert(0, 'assost-main')
from compose_docx import build_docx
base = '/opt/data/projects/assost'
img = f'{base}/tests/composed/images/p1_x35.png'
text = f'فقرة افتتاحية مترجمة تجريبية بالعربية.\n\n[IMG:{os.path.basename(img)}|full_page]\n\nفقرة ختامية بعد الرسمة.'
stats = build_docx([{'text_with_markers': text, 'images': {os.path.basename(img): img}}],
                   f'{base}/tests/composed/e2e_img_insert.docx',
                   book_title='اختبار إدراج الصور')
print('STATS:', stats)
