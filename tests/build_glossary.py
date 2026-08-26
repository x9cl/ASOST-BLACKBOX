"""بناء معجم Death March من الكتاب: اكتشاف الأسماء المتكررة + ترجمة آلية للمعجم."""
import asyncio, sys, json
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import PF
from context_bridge import ContextBridge

BASE = '/opt/data/projects/assost'

# 1) اجمع نص الكتاب كله واكتشف الأسماء المرشحة
info = PF.ProfessionalDocumentProcessor.extract_pdf_with_precision(BASE + '/book.pdf')
full = '\n'.join(ch['content'] for ch in info['chapters'])
print('corpus chars:', len(full))

cb = ContextBridge()
candidates = cb.extract_names_heuristic(full)
print('name candidates:', candidates)

TEMPLATE = '{"characters": {"English": "Arabic"}, "places": {"English": "Arabic"}, "terms": {"English": "Arabic"}}'

async def main():
    m = PF.EnhancedGeminiAPI()
    prompt = ("هذه قائمة أسماء من رواية يابانية (Death March). لكل اسم حدد النوع "
              "وشكل العربية الرسمي الموحد.\nأعد JSON فقط بالشكل:\n" + TEMPLATE +
              "\nتجاهل الكلمات التي ليست أسماء علم.\nالقائمة: " + json.dumps(candidates))
    resp, _, _ = await m.make_precision_request(
        prompt, system_instruction='You are a localization glossary builder. Output valid JSON only.')
    await m.cleanup()
    return resp

resp = asyncio.run(main())
try:
    start = resp.index('{'); end = resp.rindex('}') + 1
    data = json.loads(resp[start:end])
except Exception as e:
    print('PARSE FAIL:', str(e)[:100], '| raw:', (resp or '')[:200]); sys.exit(1)

for kind in ['characters', 'places', 'terms']:
    for en, ar in (data.get(kind) or {}).items():
        cb.register(kind, en, ar)
print('GLOSSARY SAVED:')
print(json.dumps(cb.bible, indent=1, ensure_ascii=False))
