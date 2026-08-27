"""translation_memory.py — ذاكرة الترجمة ذاتية البناء لمشروع ASOST
تنمو تلقائياً مع كل فصل مترجم وتضمن:
  1. TM قاعدة ترجمة (جمل/عبارات متكررة → ترجمتها المعتمدة)
  2. سياق متراكم: ملخص كل فصل يغذي الفصول التالية
  3. إحصاءات جودة متابعة عبر الكتاب كله
"""
import re, hashlib
from collections import Counter
from asost.memory import MemoryNamespace, SQLiteMemoryRepository


class TranslationMemory:
    def __init__(self, persist_path=None, repository=None, *, book_id='default', run_id='default',
                 agent_role='translation_memory', chapter_id='global', segment_id='global'):
        self.repository = repository or SQLiteMemoryRepository()
        self.namespace = MemoryNamespace(book_id, run_id, agent_role, chapter_id, segment_id)
        self.data = self._load() or {
            'tm': {},              # {src_hash: {'src':..., 'ar':..., 'hits': N}}
            'phrase_pairs': {},    # {en_phrase: ar_phrase} — عبارات متكررة
            'chapter_summaries': [],   # [{'n':1, 'summary':'...', 'names':[...]}]
            'rolling_context': '',     # آخر ~2000 حرف مترجم
            'stats': {'chapters': 0, 'segments': 0, 'consistency_failures': 0},
        }

    def _load(self):
        return self.repository.get(self.namespace, 'translation_memory')

    def save(self):
        self.repository.put(self.namespace, 'translation_memory', self.data)

    # ── TM: تخزين و استرجاع ────────────────────────────────────────
    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.md5(text.strip().lower().encode()).hexdigest()

    def lookup_exact(self, segment: str):
        hit = self.data['tm'].get(self._hash(segment))
        if hit:
            hit['hits'] += 1
            return hit['ar']
        return None

    def store_segment(self, src: str, ar: str):
        h = self._hash(src)
        if h not in self.data['tm']:
            self.data['tm'][h] = {'src': src[:500], 'ar': ar[:500], 'hits': 1}
            self.data['stats']['segments'] += 1

    def learn_phrase_pairs(self, src: str, ar: str):
        """يلتقط العبارات المتكررة (تحيات، تعبيرات راسخة) ويوحد ترجمتها."""
        patterns = [
            (r'"([^"]{5,80})"', None),
        ]
        # تعبيرات متكررة شائعة في الروايات
        for pat in [r'\b(I see\.[^.]*?)', r'\b([A-Z][a-z]+-sama\b)', r'\b(Level \d+\b)']:
            pass  # التوسعة لاحقاً — الأساس الآن الجمل المكررة
        key_phrases = ['I see.', 'Is that so?', 'Welcome back', 'Long time no see']
        for ph in key_phrases:
            if ph in src and ph not in self.data['phrase_pairs']:
                # خذ الجملة العربية المقابلة تقريبياً (نفس الترتيب)
                self.data['phrase_pairs'][ph] = '__PENDING__'

    # ── السياق المتدفق ─────────────────────────────────────────────
    def append_translated(self, ar_text: str):
        self.data['rolling_context'] = (
            (self.data['rolling_context'] + '\n' + ar_text)[-2500:]
        )

    def get_context_prompt(self) -> str:
        parts = []
        if self.data['chapter_summaries']:
            last = self.data['chapter_summaries'][-3:]
            parts.append('ملخص آخر فصول (للاتساق):')
            for s in last:
                parts.append(f"  • فصل {s['n']}: {s['summary'][:200]}")
        if self.data['rolling_context']:
            parts.append('نهاية النص المترجم السابق مباشرةً:')
            parts.append('  ' + self.data['rolling_context'][-800:])
        return '\n'.join(parts)

    # ── ملخصات الفصول ──────────────────────────────────────────────
    def record_chapter(self, n: int, summary: str, names: list = None):
        self.data['chapter_summaries'].append({'n': n, 'summary': summary, 'names': names or []})
        self.data['stats']['chapters'] += 1

    def summary_prompt_task(self, chapter_text_ar: str) -> str:
        return ("لخص هذا الفصل في 3-4 جمل عربية تركز على: الأحداث الرئيسية، "
                "الأسماء الجديدة الظاهرة، مكان الأحداث.\n\n" + chapter_text_ar[:3000])

    # ── إحصاءات ────────────────────────────────────────────────────
    def stats(self) -> dict:
        s = dict(self.data['stats'])
        s['tm_entries'] = len(self.data['tm'])
        s['phrases'] = len(self.data['phrase_pairs'])
        s['chapters_recorded'] = len(self.data['chapter_summaries'])
        return s

    def save_full(self):
        self.save()
