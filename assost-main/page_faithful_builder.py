"""page_faithful_builder.py — الاستراتيجية الجديدة: البناء الأمين للصفحة
بدل "نص مترجم ثم لصق صور"، نبني المستند صفحة-بصفحة مطابقاً للأصل:
  • كل صفحة أصلية = وحدة مستقلة تحتفظ بترتيب عناصرها (نص/صورة)
  • الصفحات الممسوحة بالكامل (illustrations) تُدرج كصفحات صور كاملة
  • الصفحات النصية تُترجم ثم تُعاد لبنائها بنفس حدود الفقرة
  • التحقق النهائي: مقارنة عدد/ترتيب الصفحات والعناصر مع الأصل
"""
import os
import fitz


class PageFaithfulBuilder:
    def __init__(self, pdf_path, images_dir):
        self.pdf_path = pdf_path
        self.images_dir = images_dir

    def analyze(self):
        """يحلل الكتاب الأصلي إلى وحدات صفحات مع تصنيف كل صفحة."""
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from image_aware_extract import extract_page_flow

        doc = fitz.open(self.pdf_path)
        units = []
        for pi in range(len(doc)):
            flow = extract_page_flow(self.pdf_path, pi, self.images_dir)
            imgs = [it for it in flow['flow'] if it['type'] == 'image']
            txts = [it for it in flow['flow'] if it['type'] == 'text']
            total_txt = sum(len(t['text']) for t in txts)
            has_fullpage = any(i.get('class') == 'full_page' and i['w'] >= 300 for i in imgs)
            if has_fullpage and total_txt < 100:
                kind = 'illustration'      # صفحة رسمة كاملة
            elif total_txt >= 100:
                kind = 'text'              # صفحة نصية (قد تحتوي صوراً صغيرة)
            else:
                kind = 'empty'
            units.append({'page': pi + 1, 'kind': kind,
                          'flow': flow, 'text_chars': total_txt,
                          'images': imgs})
        doc.close()
        return units

    def build_plan(self, units):
        """خطة البناء: تسلسل الصفحات كما في الأصل مع ما تحتويه كل واحدة."""
        plan = []
        for u in units:
            if u['kind'] == 'empty':
                continue
            if u['page'] == 1:   # صفحة 1 = الغلاف — يُدرج مرة واحدة فقط كغلاف
                continue
            entry = {'page': u['page'], 'kind': u['kind']}
            if u['kind'] == 'illustration':
                big = max(u['images'], key=lambda i: i['w'] * i['h'])
                entry['image'] = os.path.basename(big['path'])
            else:
                entry['text_markers'] = _merge_text(u['flow'].get('flow', []))
            plan.append(entry)
        return plan


def _merge_text(flow):
    parts = [it['text'] for it in flow if it['type'] == 'text']
    return '\n\n'.join(parts)
