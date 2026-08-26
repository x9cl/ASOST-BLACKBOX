"""اختبار تركيبي كامل (E2E): استخراج واعٍ بالصور → ترجمة العينة → تركيب DOCX بالصور.
يستهلك ~1-2 طلب API."""
import asyncio, sys, os
sys.path.insert(0, '/opt/data/projects/assost/assost-main')

BASE = '/opt/data/projects/assost'
OUT = f'{BASE}/tests/composed'
os.makedirs(f'{OUT}/images', exist_ok=True)

import PF
from image_aware_extract import extract_page_flow
from compose_docx import build_docx, IMG_MARK

async def main():
    # 1) استخراج صفحة الغلاف + صفحة 20 مع خريطة التدفق
    cover = extract_page_flow(f'{BASE}/book.pdf', 0, f'{OUT}/images')
    cover_img = next(it['path'] for it in cover['flow'] if it['type'] == 'image')

    page20 = extract_page_flow(f'{BASE}/book.pdf', 19, f'{OUT}/images')
    text = page20['text_with_markers']
    print('extracted blocks:', len(page20['flow']))

    # 2) ترجمة النص (مع إبقاء علامات الصور كما هي)
    m = PF.EnhancedGeminiAPI()
    engine = PF.CompleteTranslationEngine(m)
    # نفصل علامات الصور عن النص قبل الترجمة ثم نعيدها
    segments = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if IMG_MARK.fullmatch(block):
            segments.append(("img", block))
        else:
            segments.append(("txt", block))

    translated_segments = []
    for kind, block in segments:
        if kind == "img":
            translated_segments.append(block)
        else:
            try:
                tr, _, _ = await engine.translate_with_completion_guarantee(block)
                translated_segments.append(tr or block)
            except Exception as e:
                print('translate fail:', str(e)[:80])
                translated_segments.append(block)
    await m.cleanup()

    translated_text = "\n\n".join(translated_segments)
    print('translated blocks:', len(translated_segments))

    # 3) تركيب DOCX
    images_map = {os.path.basename(it['path']): it['path']
                  for it in page20['flow'] if it['type'] == 'image'}
    pages = [{"text_with_markers": translated_text, "images": images_map}]
    stats = build_docx(pages, f'{OUT}/e2e_page20.docx',
                       book_title="Death March — المجلد الأول",
                       cover_image=cover_img)
    print('STATS:', stats)
    print('E2E OK:', os.path.getsize(f'{OUT}/e2e_page20.docx'), 'bytes')

asyncio.run(main())
