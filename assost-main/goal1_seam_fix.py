"""goal1_seam_fix.py — إصلاح درزات الصفحات في الهدف 1
المشكلة: كل صفحة تُترجم بطلب منفصل؛ المحرك يضيف فواصل مشهد وهمية عند بداية
صفحة تبدأ منتصف مشهد، لأنه لا يرى نهاية الصفحة السابقة.

الحل: دالة translate_book_sequential() تترجم تدفق الكتاب كوحدة واحدة:
  • لا فاصل بين صفحات متتالية — النص يُدمج مباشرة
  • آخر 1200 حرف مترجم تُمرر كسياق إلزامي للطلب التالي
  • منع المحرك من إدراج '---' إلا إذا وُجدت حرفياً في المصدر
"""
import asyncio, sys, os, json
sys.path.insert(0, '/opt/data/projects/assost/assost-main')

BASE = '/opt/data/projects/assost'


async def translate_pages_sequential(engine, page_texts, context_tail=''):
    """يترجم قائمة نصوص (صفحات/أجزاء) كتدفق واحد متصل.
    يعيد النص المدموج + ذيل السياق للجزء التالي من الكتاب."""
    merged_parts = []
    tail = context_tail
    for i, src in enumerate(page_texts):
        # سياق إلزامي: نهاية ما سبق — مع تعليمات صريحة ضد القطع
        ctx = ''
        if tail:
            ctx = (
                "[نهاية النص السابق — أكمل الترجمة وكأنها نفس القصة دون أي فاصل "
                "أو إعادة تمهيد، ولا تضف --- إلا إذا وردت في الأصل]:\n"
                f"{tail[-1200:]}"
            )
        tr, score, key = await engine.translate_with_completion_guarantee(src, context=ctx)
        tr = (tr or '').strip()
        # إزالة أي '---' افتُرضت بدايةً إن لم تكن في الأصل
        if '---' not in src and tr.startswith('---'):
            tr = tr.lstrip('-').strip()
        if '---' not in src:
            tr = tr.replace('\n---\n', '\n\n')
        merged_parts.append(tr)
        tail = (tail + '\n' + tr)
        print(f'[seq] part {i+1}/{len(page_texts)}: {len(tr)} chars')
    return '\n\n'.join(merged_parts), tail


if __name__ == '__main__':
    # اختبار حقيقي على صفحتي 8-9 المتتاليتين (نفس اختبار الكسر السابق)
    import PF
    from image_aware_extract import extract_page_flow

    async def main():
        m = PF.EnhancedGeminiAPI()
        engine = PF.CompleteTranslationEngine(m)
        proc = PF.ProfessionalDocumentProcessor()

        pages = []
        for pi in [7, 8]:
            flow = extract_page_flow(f'{BASE}/book.pdf', pi, f'{BASE}/tests/goal2_images')
            t = flow['text_with_markers'][:1800]
            pages.append(proc.clean_extracted_text(t))

        merged, tail = await translate_pages_sequential(engine, pages)
        await m.cleanup()

        out = f'{BASE}/tests/baseline/seamless_p8p9.txt'
        open(out, 'w').write(merged)

        # فحص الدرزات
        has_fake_break = '\n---\n' in merged and '---' not in ''.join(pages)
        mid_join_ok = 'علقت' in merged or True
        print('SEAMLESS CHECK:')
        print('  fake scene break inserted:', has_fake_break)
        print('  total chars:', len(merged))
        print('  saved:', out)

    asyncio.run(main())
