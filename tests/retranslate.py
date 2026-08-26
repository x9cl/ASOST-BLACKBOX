import asyncio, sys, json
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import PF

BASE = '/opt/data/projects/assost'
results = {}

async def main():
    m = PF.EnhancedGeminiAPI()
    engine = PF.CompleteTranslationEngine(m)
    cb = engine.context_bridge
    for name in ['text_p20', 'text_p27', 'text_p30']:
        src = open(f'{BASE}/tests/samples/{name}.txt').read()
        tr, score, key = await engine.translate_with_completion_guarantee(src[:1800])
        open(f'{BASE}/tests/baseline/{name}_ar_v2.txt', 'w').write(tr or '')
        chk = cb.consistency_check(src[:1800], tr or '') if cb else {'passed': True, 'issues': []}
        results[name] = {'chars': len(tr or ''), 'consistency': chk}
        print(name, '| chars:', len(tr or ''), '| consistent:', chk['passed'], '| issues:', len(chk['issues']))
    await m.cleanup()
    json.dump(results, open(f'{BASE}/tests/baseline/v2_results.json', 'w'), indent=1, ensure_ascii=False)
asyncio.run(main())
