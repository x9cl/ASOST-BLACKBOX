"""e2e_agents_test.py — اختبار شامل لمنظومة ASOST-agents على صفحات حقيقية.

يترجم صفحات [7, 8, 9] من book.pdf عبر ASOSTOrchestrator.translate_page
(ترجمة → نقد خفيف → قرار/نقد عميق) مع context تسلسلي بين الصفحات،
يقيس التوقيتات، ويحفظ النتائج في asost/e2e_results.json.
"""
import os
import sys
import json
import time

BASE = '/opt/data/projects/assost'
for p in (f'{BASE}/assost-main', f'{BASE}/hermes', f'{BASE}/asost', BASE):
    if p not in sys.path:
        sys.path.insert(0, p)

if not os.environ.get('HERMES_HOME'):
    os.environ['HERMES_HOME'] = f'{BASE}/hermes-home'
if not os.environ.get('OPENROUTER_API_KEY'):
    env = f'{BASE}/assost-main/.env'
    if os.path.exists(env):
        for line in open(env):
            if line.startswith('OPENROUTER_API_KEY='):
                os.environ['OPENROUTER_API_KEY'] = line.split('=', 1)[1].strip()
                break

from deterministic_composer import analyze_pages  # noqa: E402
from orchestrator import ASOSTOrchestrator        # noqa: E402

PAGES = [7, 8, 9]
OUT_PATH = f'{BASE}/asost/e2e_results.json'


def get_page_texts():
    units = analyze_pages(f'{BASE}/book.pdf', f'{BASE}/tests/fullbook/images')
    by_page = {}
    for u in units:
        if u['kind'] == 'text':
            by_page[u['page']] = '\n\n'.join(
                i['text'] for i in u['flow'] if i['type'] == 'text')
    return by_page


def main():
    texts = get_page_texts()
    missing = [p for p in PAGES if p not in texts]
    if missing:
        raise RuntimeError(f'missing text pages: {missing}')

    gemini_ref = json.load(open(f'{BASE}/tests/fullbook/paged_translations.json'))

    orch = ASOSTOrchestrator()
    tail = ''
    results = []
    t_total0 = time.time()

    for pg in PAGES:
        src = texts[pg]
        ctx = f'[Context from previous page — continue the same story]:\n{tail[-1000:]}' if tail else ''
        print(f'=== PAGE {pg} ({len(src)} chars) ===', flush=True)
        t0 = time.time()
        decision = orch.translate_page(pg, src, context=ctx)
        dt = round(time.time() - t0, 1)

        tr = decision.get('translation', '')
        gref = gemini_ref.get(str(pg), '')
        rec = {
            'page': pg,
            'decision': decision.get('decision'),
            'light_score': decision.get('light_score'),
            'deep_score': decision.get('deep_score'),
            'best_score': decision.get('best_score'),
            'revision_rounds': decision.get('revision_rounds', 0),
            'light_verdict': {k: v for k, v in decision.get('light', {}).items()
                              if isinstance(v, (str, int, float))},
            'src_chars': len(src),
            'translation_chars': len(tr),
            'gemini_chars': len(gref),
            'secs': dt,
        }
        results.append(rec)
        print(f'page {pg}: decision={rec["decision"]} score={rec["light_score"] or rec["deep_score"]} '
              f'len={len(tr)} vs gemini={len(gref)} secs={dt}', flush=True)
        tail = tr[-1200:]

        json.dump({'total_secs_so_far': round(time.time() - t_total0, 1),
                   'pages': results},
                  open(OUT_PATH, 'w'), ensure_ascii=False, indent=2)

    total = round(time.time() - t_total0, 1)
    json.dump({'pages_requested': PAGES,
               'total_secs': total,
               'pages': results},
              open(OUT_PATH, 'w'), ensure_ascii=False, indent=2)
    print(f'DONE: {len(results)} pages in {total}s → {OUT_PATH}')


if __name__ == '__main__':
    main()
