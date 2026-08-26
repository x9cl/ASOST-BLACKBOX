import asyncio, sys
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import PF
from context_bridge import ContextBridge

cb = ContextBridge()
cb.register('characters', 'Satou', 'ساتو')
cb.register('characters', 'Liza', 'ليزا')

src_text = ('Satou checked his map again. Liza watched the road ahead. '
            '"We should reach the city by nightfall," Satou said quietly.')

async def main():
    m = PF.EnhancedGeminiAPI()
    engine = PF.CompleteTranslationEngine(m)
    bridge_ok = engine.context_bridge is not None
    chars = list(engine.context_bridge.bible['characters'].keys()) if engine.context_bridge else []
    print('BRIDGE:', bridge_ok, '| chars:', chars)
    tr, score, key = await engine.translate_with_completion_guarantee(src_text)
    await m.cleanup()
    print('TRANSLATION:', (tr or '')[:300])
    ok = cb.consistency_check(src_text, tr or '')
    print('CONSISTENCY:', ok)

asyncio.run(main())
