import asyncio, sys, json
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import PF
from image_aware_extract import extract_page_flow
from context_bridge import ContextBridge

BASE = '/opt/data/projects/assost'

cb = ContextBridge()
cb.register('characters', 'Satou', 'ساتو')
cb.register('characters', 'Zena', 'زينا')

async def main():
    m = PF.EnhancedGeminiAPI()
    engine = PF.CompleteTranslationEngine(m)
    # ترجمة صفحتين متتاليتين كتدفق واحد مع سياق متدفق حقيقي
    outputs = []
    for pi in [7, 8]:  # صفحات 8 و9 متتاليتان قصصياً
        flow = extract_page_flow(f'{BASE}/book.pdf', pi, f'{BASE}/tests/goal2_images')
        text = flow['text_with_markers'][:1800]
        ctx = cb and None  # context comes from TM rolling inside engine
        tr, score, key = await engine.translate_with_completion_guarantee(text)
        outputs.append(tr or '')
        print(f'--- page {pi+1} done: {len(tr or "")} chars')
    await m.cleanup()

    # فحص الاتصال: نهاية ص8 مقابل بداية ص9 — هل الحوار/الحدث يتصل؟
    end8 = ' '.join(outputs[0].split())[-250:]
    start9 = ' '.join(outputs[1].split())[:250]
    print('=== نهاية صفحة 8 ===')
    print(end8)
    print('=== بداية صفحة 9 ===')
    print(start9)
    open(f'{BASE}/tests/baseline/continuity_p8p9.txt', 'w').write(outputs[0] + '\n\n' + outputs[1])
asyncio.run(main())
