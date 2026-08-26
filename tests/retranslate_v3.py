import asyncio, sys, json
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import PF
from compare import compare

BASE = '/opt/data/projects/assost'
results = {}

async def main():
    m = PF.EnhancedGeminiAPI()
    engine = PF.CompleteTranslationEngine(m)
    cb = engine.context_bridge
    print('few-shots loaded:', len(cb.bible.get('few_shot_examples', [])))
    for name in ['text_p20', 'text_p27', 'text_p30']:
        src = open(f'{BASE}/tests/samples/{name}.txt').read()
        tr, score, key = await engine.translate_with_completion_guarantee(src[:1800])
        v3 = f'{BASE}/tests/baseline/{name}_ar_v3.txt'
        open(v3, 'w').write(tr or '')
        # quality vs original source
        q = compare(f'{BASE}/tests/baseline/{name}_cleaned_src.txt', v3)
        chk = cb.consistency_check(src[:1800], tr or '') if cb else {'passed': True}
        results[name] = {'score': q['score_100'], 'consistent': chk['passed']}
        print(f'{name}: score={q["score_100"]} consistent={chk["passed"]}')
    avg = sum(r['score'] for r in results.values()) / len(results)
    cons = all(r['consistent'] for r in results.values())
    print(f'V3 AVERAGE: {avg:.1f}/100 | consistency: {cons}')
    json.dump(results, open(f'{BASE}/tests/baseline/v3_results.json', 'w'), indent=1)
    await m.cleanup()
asyncio.run(main())
