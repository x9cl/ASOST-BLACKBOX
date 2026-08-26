"""خط الأساس: ترجمة العينات النصية بالمحرك الحالي.
يستهلك ~3-6 طلبات API فقط."""
import asyncio, sys, json, os
sys.path.insert(0, '/opt/data/projects/assost/assost-main')

BASE = '/opt/data/projects/assost'
SAMPLES = f'{BASE}/tests/samples'
OUT = f'{BASE}/tests/baseline'
os.makedirs(OUT, exist_ok=True)

import PF

async def main():
    m = PF.EnhancedGeminiAPI()
    engine = PF.CompleteTranslationEngine(m)
    proc = PF.ProfessionalDocumentProcessor()
    results = {}
    for name in ['text_p20', 'text_p27', 'text_p30']:
        src = open(f'{SAMPLES}/{name}.txt').read()
        cleaned = proc.clean_extracted_text(src)
        try:
            translated, score, key = await engine.translate_with_completion_guarantee(cleaned)
            results[name] = {"source_chars": len(cleaned),
                             "translated_chars": len(translated or ""),
                             "quality_score": score}
            open(f'{OUT}/{name}_ar.txt', 'w').write(translated or "")
            open(f'{OUT}/{name}_cleaned_src.txt', 'w').write(cleaned)
            print(f'{name}: {len(cleaned)} -> {len(translated or "")} chars (score={score})')
        except Exception as e:
            results[name] = {"error": str(e)[:200]}
            print(f'{name}: FAILED - {str(e)[:120]}')
    await m.cleanup()
    json.dump(results, open(f'{OUT}/results.json', 'w'), indent=2)
    print('BASELINE DONE')

asyncio.run(main())
