"""context_image_placer.py — v2: وضع الصور تلقائياً حسب السياق الدلالي
الاستراتيجية المحسنة:
  1. لكل صورة، خذ الجملة المصدرية السابقة لها في الأصل
  2. ترجمها مسبقاً؟ لا — استخدم محاذاة الأرقام والأسماء العلم المشتركة
  3. إن لم توجد مفاتيح رقمية، استخدم ترتيب الفصول: الصور الافتتاحية قبل النص،
     وصور داخل الفصول تُدرج عند أفضل تطابق أو بين فقرتين متتاليتين منطقياً.
"""
import re
import os
from difflib import SequenceMatcher


def os_path_name(p: str) -> str:
    return p.replace('\\', '/').split('/')[-1]


class ContextImagePlacer:
    def __init__(self, original_flow_pages, translated_text):
        self.pages = original_flow_pages
        self.translated = translated_text

    def _collect(self):
        """يجمع كل صور غير الزخرفية مع سياقها."""
        items = []
        for pi, page in enumerate(self.pages):
            flow = page['flow']
            for idx, it in enumerate(flow):
                if it['type'] != 'image':
                    continue
                cls = it.get('class', '')
                if cls == 'decoration':
                    continue
                before = ' '.join(x['text'] for x in flow[:idx] if x['type'] == 'text')
                after = ' '.join(x['text'] for x in flow[idx + 1:] if x['type'] == 'text')
                # إذا كانت صفحة الصورة فارغة نصياً: استخدم نهاية الصفحة السابقة وبداية التالية
                if not before and pi > 0:
                    prev_texts = [x['text'] for x in self.pages[pi - 1]['flow'] if x['type'] == 'text']
                    before = ' '.join(prev_texts)[-300:]
                if not after and pi + 1 < len(self.pages):
                    next_texts = [x['text'] for x in self.pages[pi + 1]['flow'] if x['type'] == 'text']
                    after = ' '.join(next_texts)[:300]
                items.append({'page': pi + 1, 'path': it['path'], 'class': cls,
                              'before': before[-300:], 'after': after[:300]})
        return items

    def _match_position(self, src_before: str):
        """يحدد موضع الإدراج بالعربية: بحث عن آخر جملة مترجمة تطابق نهاية src_before.
        يعيد (position, confidence)."""
        t = self.translated
        # مفتاح قوي: أرقام في آخر 150 حرف (مع تطبيع الأرقام الشرقية ٠-٩)
        EAST = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
        t_norm = t.translate(EAST)
        nums = re.findall(r'\d+', src_before[-400:])
        if not nums:
            return None, 'none'
        best_pos, best_score = None, 0
        for n in set(nums):
            for m in re.finditer(re.escape(n), t_norm):
                pos = m.end()
                # تحقق سياقي: هل الأرقام الأخرى موجودة قريباً؟
                window = t_norm[max(0, pos - 500):pos + 200]
                score = sum(1 for x in set(nums) if x in window)
                if score > best_score:
                    best_pos, best_score = pos, score
        if best_pos is not None and best_score >= max(1, len(set(nums)) // 2):
            return best_pos, 'numbers'
        return None, 'none'

    def place_all(self) -> str:
        items = self._collect()
        openers = [x for x in items if x['page'] <= 6 and x['page'] > 1]  # الافتتاحيات بلا الغلاف
        inline = [x for x in items if x['page'] > 6]         # صور داخل النص

        result = self.translated
        log = []

        # 1) الرسومات الداخلية أولاً — حسب السياق
        for item in inline:
            name = os_path_name(item['path'])
            marker = f'[IMG:{name}|{item["class"]}]'
            pos, how = self._match_position(item['before'])
            if pos:
                # التزم بنهاية جملة/فقرة: أقرب نهاية جملة بعد النقطة المطابقة
                window_end = min(len(result), pos + 400)
                ends = [m2.end() for m2 in re.finditer(r'[.!؟?][\n\s]*', result[pos:window_end])]
                para_breaks = [m2.end() for m2 in re.finditer(r'\n\s*\n', result[pos:window_end])]
                # ابحث عن نهاية الفقرة التي تُكمل الفكرة: آخر فاصل فقرة خلال 700 حرف
                # (الفكرة قد تمتد لعدة جمل — الصورة توضع بعد اكتمالها لا في منتصفها)
                wide_end = min(len(result), pos + 700)
                all_para_breaks = [m2.end() for m2 in re.finditer(r'\n\s*\n', result[pos:wide_end])]
                if all_para_breaks:
                    pos = pos + max(all_para_breaks)
                elif candidates:
                    pos = pos + candidates[0]
                result = result[:pos] + f'\n\n{marker}\n\n' + result[pos:]
                log.append(f'{name} -> pos {pos} ({how})')
            else:
                log.append(f'{name} -> NO MATCH, skipped (manual)')

        # 2) رسومات الافتتاح — بعد الغلاف مباشرة، كل واحدة صفحة (نفس ترتيب الأصل)
        opener_block = '\n\n'.join(
            f'[IMG:{os_path_name(x["path"])}|{x["class"]}]' for x in openers)
        if opener_block:
            # أدرجها بعد أول عنوان/بداية النص مباشرة (قبل التمهيد)
            first_heading = result.find('التمهيد')
            insert_at = first_heading if first_heading > 0 else 0
            result = result[:insert_at] + opener_block + '\n\n' + result[insert_at:]
            log.append(f'{len(openers)} openers inserted at pos {insert_at}')

        for l in log:
            print('[ContextPlacer]', l)
        return result
