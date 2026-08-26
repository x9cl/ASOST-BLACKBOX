"""اختبار تكامل كامل: create_novel_document مع علامات [IMG:] و images_map."""
import sys, os
sys.path.insert(0, '/opt/data/projects/assost/assost-main')

import PF

base = '/opt/data/projects/assost'
img = f'{base}/tests/composed/images/p1_x35.png'
img_name = os.path.basename(img)

chapters = [{
    "title": "الفصل الأول — اختبار",
    "translated_content": (
        "بدا الأمر وكأنه ميزة من ميزات الواقع المعزز، تشبه ألعاب الهواتف الذكية.\n\n"
        f"[IMG:{img_name}|full_page]\n\n"
        "«أم المفترض أن تكون هذه لعبة؟» أنينتُ بمرارة، محاولاً خداع أطرافي الواهنة لتتحرك."
    ),
    "images_map": {img_name: img},
}]

out = f'{base}/tests/composed/integrated_test.docx'
result = PF.EnhancedDocumentGenerator.create_novel_document(
    chapters, out, book_title="اختبار التكامل", author="Lain",
    table_of_contents=[{"arabic_title": "الفصل الأول — اختبار"}])
print('RESULT:', result)
print('SIZE:', os.path.getsize(out), 'bytes')
