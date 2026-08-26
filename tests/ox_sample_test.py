"""ox_sample_test.py — ترجمة عينة ASOST كاملة بـ ox-alpha عبر openrouter_engine
العينة: صفحات 7-9 (Prologue) — نفس عينة الجودة القياسية.
يقيس: الوقت الكلي، الوقت/صفحة، ويحفظ النتائج في paged_translations_ox.json
"""
import sys, os, json, time, asyncio

BASE = '/opt/data/projects/assost'
sys.path.insert(0, f'{BASE}/assost-main')

from dotenv import load_dotenv  # noqa
load_dotenv(f'{BASE}/assost-main/.env') if os.path.exists(f'{BASE}/assost-main/.env') else None
# manual .env load (dotenv قد لا يكون مثبتاً)
if not os.environ.get('OPENROUTER_API_KEY'):
    for line in open(f'{BASE}/assost-main/.env'):
        if line.startswith('OPENROUTER_API_KEY='):
            os.environ['OPENROUTER_API_KEY'] = line.split('=', 1)[1].strip()
            break

from deterministic_composer import analyze_pages          # noqa
from openrouter_engine import EnhancedOpenRouterAPI, CompleteTranslationEngine  # noqa


async def main():
    proc_pages = [7, 8, 9]           # العينة القياسية
    tr_path = f'{BASE}/tests/fullbook/paged_translations.json'
    gemini_tr = json.load(open(tr_path))
    out_path = f'{BASE}/tests/fullbook/paged_translations_ox.json'

    units = analyze_pages(f'{BASE}/book.pdf', f'{BASE}/tests/fullbook/images')
    plan = [{'page': u['page'],
             'text': '\n\n'.join(i['text'] for i in u['flow'] if i['type'] == 'text')}
            for u in units if u['page'] in proc_pages]

    api = EnhancedOpenRouterAPI()
    eng = CompleteTranslationEngine(api)
    results, timings = {}, []
    tail = ''
    t_all0 = time.time()

    try:
        for e in plan:
            src = e['text']
            ctx = f'[نهاية النص السابق — أكمل نفس القصة بلا فواصل]:\n{tail[-1000:]}' if tail else ''
            print(f'translating page {e["page"]} ({len(src)} chars)...')
            t0 = time.time()
            tr, dt, _ = await eng.translate_with_completion_guarantee(src, context=ctx)
            dt_page = round(time.time() - t0, 1)
            if not tr:
                print(f'  FAILED page {e["page"]}')
                continue
            results[str(e['page'])] = tr
            timings.append(dt_page)
            tail = (tail + '\n' + tr)[-1200:]
            print(f'  done: {dt_page}s | {len(tr)} chars | speed {round(len(src)/dt_page)} src-chars/s')
            json.dump(results, open(out_path, 'w'), ensure_ascii=False)  # حفظ تدريجي
    finally:
        await api.cleanup()

    total = round(time.time() - t_all0, 1)
    n = len(timings)
    print('\n' + '=' * 50)
    print(f'TOTAL: {total}s for {n} pages → {round(total/n,1)}s/page')
    print(f'sample size: {sum(len(p["text"]) for p in plan)} src chars')
    # مقارنة سريعة مع Gemini المخزنة (طول النص كمؤشر اكتمال)
    for k, v in results.items():
        g = len(gemini_tr.get(k, ''))
        print(f'page {k}: ox={len(v)} chars vs gemini={g} chars ({round(len(v)/max(g,1)*100)}%)')


asyncio.run(main())
