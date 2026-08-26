"""goal1_fullbook.py — ترجمة الكتاب كاملاً كتدفق متصل (الهدف 1 النهائي)
يترجم كل صفحات الكتاب بالتسلسل مع جسر السياق + المعجم + ذاكرة الترجمة،
ثم يركّب DOCX + PDF نهائيين ويقيس الاتساق عبر الكتاب كله.
استهلاك API محكوم: صفحة واحدة (~1500 حرف) لكل طلب.
"""
import asyncio, sys, os, json, time
sys.path.insert(0, '/opt/data/projects/assost/assost-main')

BASE = '/opt/data/projects/assost'
OUT = f'{BASE}/tests/fullbook'
os.makedirs(f'{OUT}/images', exist_ok=True)

import PF
from image_aware_extract import extract_page_flow
from goal1_seam_fix import translate_pages_sequential
from compose_docx import build_docx
from arabic_pdf import build_pdf


async def main():
    import fitz
    doc = fitz.open(f'{BASE}/book.pdf')
    n_pages = len(doc)
    doc.close()

    m = PF.EnhancedGeminiAPI()
    engine = PF.CompleteTranslationEngine(m)
    proc = PF.ProfessionalDocumentProcessor()

    # الغلاف من صفحة 1
    cover_flow = extract_page_flow(f'{BASE}/book.pdf', 0, f'{OUT}/images')
    cover_img = next((it['path'] for it in cover_flow['flow'] if it['type'] == 'image'), None)

    # استخراج كل الصفحات النصية (7..30 — بعد الأغلفة) وتنظيفها
    page_texts = []
    for pi in range(6, n_pages):   # الصفحات 7-30
        flow = extract_page_flow(f'{BASE}/book.pdf', pi, f'{OUT}/images')
        t = proc.clean_extracted_text(flow['text_with_markers'])
        if len(t.strip()) > 100:
            page_texts.append((pi + 1, t))
    print(f'FULLBOOK: {len(page_texts)} text pages to translate')

    results = []
    tail = ''
    t0 = time.time()
    for i, (page_no, src) in enumerate(page_texts):
        try:
            merged, tail = await translate_pages_sequential(engine, [src], context_tail=tail)
            results.append((page_no, merged))
            print(f'[{i+1}/{len(page_texts)}] p{page_no}: {len(merged)} chars '
                  f'({time.time()-t0:.0f}s elapsed)')
        except Exception as e:
            print(f'[!] p{page_no} FAILED: {str(e)[:80]}')
            results.append((page_no, f'[صفحة {page_no}: فشل الترجمة]'))
            # انتظار قصير عند أي خطأ (احترام حدود المعدل) ثم استمرار
            await asyncio.sleep(20)

    await m.cleanup()

    # دمج الكتاب كاملاً
    full_text = '\n\n'.join(tr for _, tr in results)
    open(f'{OUT}/full_book_ar.txt', 'w').write(full_text)

    # فحص الاتساق النهائي عبر الكتاب كله
    cb = engine.context_bridge
    consistency = cb.consistency_check(full_text, full_text) if cb else {'passed': True}
    names_found = {en: (info['ar'] if isinstance(info, dict) else info)
                   for en, info in (cb.bible['characters'].items() if cb else {})}
    name_presence = {ar: full_text.count(ar) for ar in names_found.values()}

    # تركيب DOCX + PDF مع صور الكتاب
    images_map = {}
    for il in json.loads(json.dumps([{'name': os.path.basename(p), 'path': p}
                                     for p in [cover_img] if p])):
        images_map[il['name']] = il['path']

    pages_for_doc = [{'text_with_markers': full_text, 'images': images_map}]
    stats_docx = build_docx(pages_for_doc, f'{OUT}/full_book.docx',
                            book_title='Death March — المجلد الأول', cover_image=cover_img)
    size_pdf = build_pdf(pages_for_doc, f'{OUT}/full_book.pdf',
                         book_title='Death March — المجلد الأول', cover_image=cover_img)

    report = {
        'pages_translated': len(results),
        'total_chars': len(full_text),
        'time_seconds': round(time.time() - t0),
        'consistency_passed': consistency.get('passed'),
        'name_presence': name_presence,
        'docx_stats': stats_docx,
        'pdf_bytes': size_pdf,
    }
    json.dump(report, open(f'{OUT}/report.json', 'w'), indent=1, ensure_ascii=False)
    print('FULLBOOK DONE:', json.dumps(report, ensure_ascii=False, indent=1))


asyncio.run(main())
