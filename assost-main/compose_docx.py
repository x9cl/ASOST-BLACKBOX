"""المرحلة 2-3: مولّد DOCX عربي واعٍ بالصور — compose_docx.py
يأخذ تدفق الصفحات (نص مترجم + علامات [IMG:...]) ويبني مستنداً نهائياً:
- الصور تُدرج في مواضعها الأصلية
- دعم RTL للعربية، غلاف، فهرس بسيط"""
import os, re
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION

IMG_MARK = re.compile(r'\[IMG:([^|\]]+)(?:\|([^\]]+))?\]')


def _set_rtl(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    bidi = pPr.makeelement('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}bidi', {})
    bidi.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '1')
    pPr.append(bidi)


def build_docx(pages_flow, output_path, book_title="كتاب مترجم", cover_image=None):
    """pages_flow: قائمة صفحات، كل صفحة {"text_with_markers": str, "images": {filename: path}}"""
    doc = Document()

    # الغلاف
    if cover_image and os.path.exists(cover_image):
        doc.add_picture(cover_image, width=Inches(5.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = t.add_run(book_title)
    run.font.size = Pt(28)
    run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)
    doc.add_page_break()

    stats = {"images_inserted": 0, "images_missing": 0, "paragraphs": 0}

    for pi, page in enumerate(pages_flow):
        text = page.get("text_with_markers", "")
        images = page.get("images", {})
        for block in text.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            # هل البلوك صورة؟
            m = IMG_MARK.fullmatch(block)
            if m:
                fname, _cls = m.group(1), m.group(2)
                ipath = images.get(fname) or os.path.join(
                    os.path.dirname(output_path), 'images', fname)
                if os.path.exists(ipath):
                    doc.add_picture(ipath, width=Inches(4.5))
                    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                    stats["images_inserted"] += 1
                else:
                    stats["images_missing"] += 1
                continue
            # فقرة نص عربية
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_rtl(p)
            run = p.add_run(block)
            run.font.size = Pt(12)
            run.font.name = 'Amiri'
            stats["paragraphs"] += 1
        if pi < len(pages_flow) - 1:
            doc.add_page_break()

    doc.save(output_path)
    return stats


if __name__ == '__main__':
    # اختبار تركيبي: صفحات الغلاف + صفحة مترجمة مع صورة
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from image_aware_extract import extract_page_flow

    base = '/opt/data/projects/assost'
    out = f'{base}/tests/composed'
    os.makedirs(out, exist_ok=True)

    # غلاف (صفحة 1) + صفحة 20 كمثال نصي
    cover = extract_page_flow(f'{base}/book.pdf', 0, f'{out}/images')
    cover_img = next(it['path'] for it in cover['flow'] if it['type'] == 'image')

    pages = [{"text_with_markers": "بدا الأمر وكأنه ميزة من ميزات الواقع المعزز، تشبه تلك التي نراها في ألعاب الهواتف الذكية.\n\n«أم المفترض أن تكون هذه لعبة؟» أنينتُ بمرارة، محاولاً خداع أطرافي الواهنة لتتحرك.",
              "images": {}}]
    stats = build_docx(pages, f'{out}/test_composed.docx',
                       book_title="Death March — المجلد الأول (اختبار)",
                       cover_image=cover_img)
    print('STATS:', stats)
    print('DOCX OK:', os.path.getsize(f'{out}/test_composed.docx'), 'bytes')
