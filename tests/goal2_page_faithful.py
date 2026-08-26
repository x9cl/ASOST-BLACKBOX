"""goal2_page_faithful.py — دورة البناء الأمين: خطة → ترجمة → تركيب → تحقق"""
import asyncio, sys, os, json
sys.path.insert(0, '/opt/data/projects/assost/assost-main')

BASE = '/opt/data/projects/assost'
IMG = f'{BASE}/tests/goal2_images'

from page_faithful_builder import PageFaithfulBuilder, _merge_text

# ═══ 1) التحليل وخطة البناء ═══
builder = PageFaithfulBuilder(f'{BASE}/book.pdf', IMG)
units = builder.analyze()
plan = builder.build_plan(units)

illus_pages = [p['page'] for p in plan if p['kind'] == 'illustration']
text_pages = [p['page'] for p in plan if p['kind'] == 'text']
print(f'PLAN: {len(units)} units -> {len(illus_pages)} illustration pages {illus_pages}')
print(f'      + {len(text_pages)} text pages')
json.dump(plan, open(f'{BASE}/tests/fullbook/build_plan.json', 'w'), indent=1, ensure_ascii=False)

# ═══ 2) الترجمة المتسلسلة للصفحات النصية فقط (مع سياق متدفق) ═══
need_translation = all(not os.path.exists(f'{BASE}/tests/fullbook/paged_translations.json')
                       for _ in [0]) or True
cache = f'{BASE}/tests/fullbook/paged_translations.json'
translations = {}
if os.path.exists(cache):
    translations = json.load(open(cache))
    print(f'cache: {len(translations)} pages already translated')

missing = [str(p['page']) for p in plan if p['kind'] == 'text' and str(p['page']) not in translations]
print(f'missing pages to translate: {len(missing)}')

if missing:
    import PF
    from image_aware_extract import extract_page_flow

    async def translate_missing():
        m = PF.EnhancedGeminiAPI()
        engine = PF.CompleteTranslationEngine(m)
        proc = PF.ProfessionalDocumentProcessor()
        tail = ''
        for entry in plan:
            if entry['kind'] != 'text':
                continue
            pg = str(entry['page'])
            if pg in translations:
                tail = translations[pg][-1200:]
                continue
            src = proc.clean_extracted_text(entry['text_markers'])
            ctx = ''
            if tail:
                ctx = ('[نهاية النص السابق — أكمل نفس القصة بلا فواصل]:\n' + tail[-1000:])
            tr, _, _ = await engine.translate_with_completion_guarantee(src, context=ctx)
            translations[pg] = tr or ''
            json.dump(translations, open(cache, 'w'), ensure_ascii=False)
            tail = (tail + '\n' + (tr or ''))[-1200:]
            print(f'translated p{pg}: {len(tr or "")} chars')
        await m.cleanup()

    asyncio.run(translate_missing())

# ═══ 3) التركيب الأمين: صفحة-بصفحة بنفس ترتيب الأصل ═══
from compose_docx import build_docx
from arabic_pdf import build_pdf

cover = f'{IMG}/p1_x35.png'
images = {}
for d_ in [IMG, f'{BASE}/tests/fullbook/images']:
    if os.path.isdir(d_):
        for f in os.listdir(d_):
            images[f] = os.path.join(d_, f)

pages_out = []
for entry in plan:
    pg = str(entry['page'])
    if entry['kind'] == 'illustration':
        pages_out.append({'text_with_markers': f'[IMG:{entry["image"]}|full_page]',
                          'images': images})
    else:
        tr = translations.get(pg, '')
        pages_out.append({'text_with_markers': tr, 'images': images})

s1 = build_docx(pages_out, f'{BASE}/tests/fullbook/full_book.docx',
                book_title='Death March — المجلد الأول', cover_image=cover)
size = build_pdf(pages_out, f'{BASE}/tests/fullbook/full_book.pdf',
                 book_title='Death March — المجلد الأول', cover_image=cover)
print('DOCX:', s1)
print('PDF:', size)

# ═══ 4) التحقق الهيكلي: مطابقة الأصل ═══
import fitz
orig = fitz.open(f'{BASE}/book.pdf')
new = fitz.open(f'{BASE}/tests/fullbook/full_book.pdf')
o_imgs = [(i+1) for i in range(len(orig)) if orig[i].get_image_info()]
n_imgs = [(i+1) for i in range(len(new)) if new[i].get_image_info()]
report = {
    'orig_pages': len(orig), 'new_pages': len(new),
    'orig_image_pages': o_imgs,
    'new_image_pages': n_imgs,
    'image_pages_match': o_imgs == n_imgs[:len(o_imgs)] or set(o_imgs).issubset(set(n_imgs)),
}
json.dump(report, open(f'{BASE}/tests/fullbook/fidelity_report.json', 'w'), indent=1)
print('FIDELITY:', json.dumps(report, indent=1))
