"""ox_fullbook.py — ترجمة الكتاب كاملاً (23 صفحة نصية) بـ ox-alpha
- يستخدم paged_translations_ox.json كذاكرة (استئناف تلقائي)
- حفظ تدريجي بعد كل صفحة (لو انقطع، نكمل من حيث توقفنا)
- في النهاية: بناء PDF + DOCX نهائيين بالمؤلف الحتمي
"""
import sys, os, json, time, asyncio

BASE = '/opt/data/projects/assost'
sys.path.insert(0, f'{BASE}/assost-main')

if not os.environ.get('OPENROUTER_API_KEY'):
    for line in open(f'{BASE}/assost-main/.env'):
        if line.startswith('OPENROUTER_API_KEY='):
            os.environ['OPENROUTER_API_KEY'] = line.split('=', 1)[1].strip()
            break

from deterministic_composer import analyze_pages, build_pages_flow  # noqa
from deterministic_render import render_pdf, render_docx            # noqa
from openrouter_engine import EnhancedOpenRouterAPI, CompleteTranslationEngine  # noqa

OUT_DIR = f'{BASE}/tests/fullbook/ox_full'
os.makedirs(OUT_DIR, exist_ok=True)
TR_PATH = f'{OUT_DIR}/paged_translations_ox.json'


async def main():
    units = analyze_pages(f'{BASE}/book.pdf', f'{BASE}/tests/fullbook/images')
    text_pages = [{'page': u['page'],
                   'text': '\n\n'.join(i['text'] for i in u['flow'] if i['type'] == 'text')}
                  for u in units if u['kind'] == 'text']
    total_chars = sum(len(p['text']) for p in text_pages)
    print(f'text pages: {len(text_pages)} | {total_chars} src chars')

    results = {}
    if os.path.exists(TR_PATH):
        results = json.load(open(TR_PATH))
        print(f'resume: {len(results)} pages already done')
    gemini_ref = json.load(open(f'{BASE}/tests/fullbook/paged_translations.json'))

    api = EnhancedOpenRouterAPI()
    eng = CompleteTranslationEngine(api)
    tail = ''
    t_start = time.time()
    done_times = []
    try:
        for e in text_pages:
            pg = str(e['page'])
            if pg in results and results[pg]:
                tail = (tail + '\n' + results[pg])[-1200:]
                continue
            ctx = f'[نهاية النص السابق — أكمل نفس القصة بلا فواصل]:\n{tail[-1000:]}' if tail else ''
            print(f'page {e["page"]} ({len(e["text"])} chars)...', flush=True)
            t0 = time.time()
            tr, dt, _ = await eng.translate_with_completion_guarantee(e['text'], context=ctx)
            if not tr:
                print(f'  EMPTY result, retrying once...')
                tr, dt, _ = await eng.translate_with_completion_guarantee(e['text'], context=ctx)
            if not tr:
                print('  FAILED twice, skipping page')
                continue
            results[pg] = tr
            done_times.append(time.time() - t0)
            json.dump(results, open(TR_PATH, 'w'), ensure_ascii=False)
            eta = (len(text_pages) - len(results)) * (sum(done_times)/len(done_times))
            print(f'  ok {round(time.time()-t0,1)}s | done {len(results)}/{len(text_pages)} | ETA {round(eta/60,1)}min', flush=True)
            tail = (tail + '\n' + tr)[-1200:]
    finally:
        await api.cleanup()

    total_min = round((time.time() - t_start)/60, 1)
    print(f'\nTRANSLATION DONE: {len(results)} pages in {total_min} min')

    # ── بناء الملفات النهائية ──
    pf, rep = build_pages_flow(f'{BASE}/book.pdf', f'{OUT_DIR}/images', results)
    pdf_out = f'{OUT_DIR}/ox_full_book.pdf'
    docx_out = f'{OUT_DIR}/ox_full_book.docx'
    szp = render_pdf(pf, pdf_out, 'Death March — المجلد الأول (ترجمة ox-alpha)',
                     f'{BASE}/tests/fullbook/images/p1_x35.png')
    szd = render_docx(pf, docx_out, 'Death March — المجلد الأول (ترجمة ox-alpha)',
                      f'{BASE}/tests/fullbook/images/p1_x35.png')
    import fitz
    d = fitz.open(pdf_out)
    print(f'PDF: {pdf_out} ({szp} bytes, {len(d)} pages)')
    print(f'DOCX: {docx_out} ({szd} bytes)')
    print(f'illustration pages: {rep["illustration_pages"]} | inline: {rep["inline_images"]}')
    json.dump({'total_minutes': total_min, 'pages': len(results),
               'pdf': pdf_out, 'docx': docx_out},
              open(f'{OUT_DIR}/run_report.json', 'w'), ensure_ascii=False)


asyncio.run(main())
