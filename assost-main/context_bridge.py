"""context_bridge.py — جسر السياق الدائم لمشروع ASOST
يضمن ترابط الأسماء والأماكن والحوارات عبر الفصول والأجزاء:
  1. قاموس معجم موحد (Character/Place Bible) يُبنى قبل الترجمة ويُمرر لكل طلب
  2. نافذة سياق ممتدة: آخر ~1200 حرف مترجم + أول 300 من الفصل القادم (معاينة)
  3. فحص اتساق بعد الترجمة: هل الأسماء المعروفة ظهرت بصيغتها العربية الموحدة؟
"""
import re
from asost.memory import MemoryNamespace, SQLiteMemoryRepository

class ContextBridge:
    def __init__(self, persist_path=None, repository=None, *, book_id='default',
                 run_id='default', agent_role='context_bridge', chapter_id='global',
                 segment_id='global'):
        self.repository = repository or SQLiteMemoryRepository()
        self.namespace = MemoryNamespace(book_id, run_id, agent_role, chapter_id, segment_id)
        self.bible = self._load() or {
            'characters': {},   # {en_lower: {'ar': ..., 'variants': [...]}}
            'places': {},
            'terms': {},        # مصطلحات خاصة (كيندو، موشي...)
            'style': 'رواية خفيفة يابانية (Light Novel) — سرد متكول بضمير المتكلم',
        }

    def _load(self):
        return self.repository.get(self.namespace, 'context_bible')

    def save(self):
        self.repository.put(self.namespace, 'context_bible', self.bible)

    # ── 1) بناء المعجم قبل الترجمة ────────────────────────────────
    def build_glossary_prompt(self) -> str:
        """قسم يُحقن في system instruction لكل طلب ترجمة."""
        lines = ['\n### معجم الكتاب الموحد (التزم به حرفياً):']
        if self.bible['characters']:
            lines.append('الشخصيات:')
            for en, info in self.bible['characters'].items():
                lines.append(f"  - {en} → «{info['ar']}» (استخدم هذا الاسم دائماً)")
        if self.bible['places']:
            lines.append('الأماكن:')
            for en, ar in self.bible['places'].items():
                lines.append(f"  - {en} → «{ar}»")
        if self.bible['terms']:
            lines.append('مصطلحات ثابتة:')
            for en, ar in self.bible['terms'].items():
                lines.append(f"  - {en} → «{ar}»")
        return '\n'.join(lines) if len(lines) > 1 else ''

    def extract_names_heuristic(self, text: str) -> list:
        """يلتقط أسماء علم مرشحة (كلمات كبيرة مكررة) لبناء المعجم تلقائياً."""
        counts = {}
        for m in re.finditer(r'\b([A-Z][a-z]{2,})\b', text):
            w = m.group(1)
            if w.lower() in {'the','and','she','his','her','they','there','then','this','that','with','from'}:
                continue
            counts[w] = counts.get(w, 0) + 1
        return sorted((w for w, c in counts.items() if c >= 3), key=lambda w: -counts[w])[:15]

    def register(self, kind: str, en: str, ar: str):
        store = self.bible.setdefault(kind, {})
        if isinstance(store, dict) and not isinstance(ar, dict):
            store[en] = {'ar': ar, 'variants': []} if kind == 'characters' else ar
        self.save()

    # ── 2) نافذة السياق الممتدة ───────────────────────────────────
    def context_window(self, translated_tail: str, next_chunk_head: str = '') -> str:
        tail = (translated_tail or '')[-1200:]
        head = ('\n[بداية المقطع التالي للمعاينة فقط]:\n' + next_chunk_head[:300]) if next_chunk_head else ''
        return f"""سياق ما سبق مباشرةً (للحفاظ على الترابط — لا تترجمه، استخدمه للاتساق فقط):
{tail}{head}
{self.build_glossary_prompt()}"""

    # ── 3) فحص اتساق بعد الترجمة ─────────────────────────────────
    def consistency_check(self, source: str, translation: str) -> dict:
        issues = []
        for en, info in self.bible.get('characters', {}).items():
            if re.search(rf'\b{re.escape(en)}\b', source, re.IGNORECASE):
                ar_name = info['ar'] if isinstance(info, dict) else info
                if ar_name and ar_name not in translation:
                    issues.append(f"اسم الشخصية «{en}» يجب أن يظهر كـ«{ar_name}» ولم يوجد")
        return {"issues": issues, "passed": not issues}

    def fix_injections(self, translation: str) -> str:
        """تصحيح آلي: استبدال صيغ الاسم المخالفة بالموحدة (بدون API)."""
        for en, info in self.bible.get('characters', {}).items():
            ar = info['ar'] if isinstance(info, dict) else info
            if ar:
                translation = re.sub(rf'\b{re.escape(en)}\b', ar, translation)
        return translation


if __name__ == '__main__':
    cb = ContextBridge()
    # تسجيل أسماء من الكتاب الحالي (Death March Vol.1)
    cb.register('characters', 'Satou', 'ساتو')
    cb.register('characters', 'Zena', 'زينا')
    cb.register('characters', 'Liza', 'ليزا')
    cb.register('places', 'Shiga Kingdom', 'مملكة شيغا')
    cb.register('places', 'Seiryuu City', 'مدينة سيرييو')
    cb.register('terms', 'Kendo', 'الكيندو')
    print('glossary prompt:')
    print(cb.build_glossary_prompt())
