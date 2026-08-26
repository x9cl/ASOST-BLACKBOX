"""orchestrator.py — مدير وكلاء ASOST الدائمين.

يدير دورة الترجمة: المترجم → الناقد السريع → (الناقد العميق عند الحاجة)
مع حفظ/تحميل الحالة عبر أدوات asost_memory.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from agent_runner import build_agent, ensure_hermes_home  # noqa: F401

ACCEPT_THRESHOLD = 85
CHAT_TIMEOUT_S = 300


JSON_ONLY_RULE = ('أعد إجابتك كـ JSON واحد فقط بهذا الشكل: '
                  '{"score": <0-100>, "notes": [...]}. لا نص قبل أو بعد.')

MAX_REVISION_ROUNDS = 3
SEGMENT_CHAR_LIMIT = 1800


def _split_paragraphs(text):
    """Return non-empty paragraphs without losing dialogue line boundaries."""
    return [part.strip() for part in re.split(r"\n\s*\n", str(text))
            if part.strip()]


def _segment_source(text, limit=SEGMENT_CHAR_LIMIT):
    """Split at paragraph boundaries, then dialogue/sentence boundaries.

    Every returned unit fits the critic budget.  A single over-sized paragraph
    is split on newlines (important for dialogue), then sentences, and only as
    a last resort at a whitespace boundary.
    """
    def split_long(block):
        if len(block) <= limit:
            return [block]
        units = [u.strip() for u in re.split(
            r"(?<=\n)|(?<=[.!?؟!؛])\s+", block) if u.strip()]
        result, current = [], ""
        for unit in units:
            while len(unit) > limit:
                cut = unit.rfind(" ", 0, limit + 1)
                cut = cut if cut > 0 else limit
                prefix, unit = unit[:cut].strip(), unit[cut:].strip()
                if current:
                    result.append(current)
                    current = ""
                result.append(prefix)
            candidate = f"{current}\n{unit}" if current else unit
            if len(candidate) <= limit:
                current = candidate
            else:
                result.append(current)
                current = unit
        if current:
            result.append(current)
        return result

    chunks, current = [], ""
    for paragraph in _split_paragraphs(text):
        for unit in split_long(paragraph):
            candidate = f"{current}\n\n{unit}" if current else unit
            if len(candidate) <= limit:
                current = candidate
            else:
                chunks.append(current)
                current = unit
    if current:
        chunks.append(current)
    return chunks


_IMAGE_RE = re.compile(
    r"\[IMG:[^\]]+\]|\[\[(?:IMAGE|IMG)[^\]]*\]\]|<image\b[^>]*>|!\[[^\]]*\]\([^)]*\)",
    re.IGNORECASE)
_PROTECTED_NAME_RE = re.compile(
    r"\{\{(?:NAME|PROTECTED):[^}]+\}\}|\[\[(?:NAME|PROTECTED):[^\]]+\]\]",
    re.IGNORECASE)


def _normalise_digits(value):
    return str(value).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))


def _deterministic_checks(source, translation):
    """Cheap, deterministic completeness checks over the *entire* page."""
    source, translation = str(source), str(translation)
    src_paras, dst_paras = _split_paragraphs(source), _split_paragraphs(translation)
    src_len = len(re.sub(r"\s+", "", source))
    dst_len = len(re.sub(r"\s+", "", translation))
    ratio = dst_len / max(src_len, 1)
    prose = _PROTECTED_NAME_RE.sub("", _IMAGE_RE.sub("", translation))
    english = re.findall(r"\b[A-Za-z]{3,}\b", prose)
    checks = {
        "paragraph_coverage": len(dst_paras) >= len(src_paras),
        "english_remaining": len(english) <= max(2, src_len // 500),
        "normal_length": 0.45 <= ratio <= 2.5,
        "image_markers": _IMAGE_RE.findall(source) == _IMAGE_RE.findall(translation),
        "numbers": re.findall(r"\d+(?:[.,]\d+)*", _normalise_digits(source))
                   == re.findall(r"\d+(?:[.,]\d+)*", _normalise_digits(translation)),
        "protected_names": _PROTECTED_NAME_RE.findall(source)
                           == _PROTECTED_NAME_RE.findall(translation),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "source_paragraphs": len(src_paras),
            "translation_paragraphs": len(dst_paras),
            "length_ratio": round(ratio, 3), "english_words": english}


def _extract_json(text):
    """استخراج أول كائن JSON متوازن الأقواس من رد الوكيل.

    - واعٍ للسلاسل النصية (أقواس داخل نص لا تُحتسب).
    - يبحث عن أول { ... } متوازن حتى داخل نص طويل مختلط.
    """
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if in_str:
                if c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def _find_score(data):
    """بحث تكراري (recursive) عن أول قيمة 'score' صالحة داخل القواميس المتداخلة."""
    if isinstance(data, dict):
        for key in ("score", "overall_score", "total"):
            if key in data:
                return data[key]
        # مفتاح 'overall' قد يحمل القيمة مباشرة أو يكون قاموساً متداخلاً
        if "overall" in data and not isinstance(data["overall"], (dict, list)):
            return data["overall"]
        for v in data.values():
            found = _find_score(v)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_score(item)
            if found is not None:
                return found
    return None


def _extract_score(data):
    """استخرج درجة 0-100 من أي بنية JSON (بحث تكراري في المستويات المتداخلة).

    تطبيع المقياس: أي درجة ≤ 10 تُضرب في 10.
    """
    val = _find_score(data)
    if isinstance(val, str):
        m = re.search(r"[\d.]+", val)
        val = float(m.group(0)) if m else None
    try:
        val = float(val)
    except (TypeError, ValueError):
        return None
    if val <= 10:
        val *= 10
    return int(round(val))


def _memory_path():
    import os
    return "/opt/data/projects/assost/asost_memory.json"


class ASOSTOrchestrator:
    """Orchestrator — يبني الوكلاء الدائمين مرة واحدة ويدير خط الترجمة."""

    def __init__(self):
        ensure_hermes_home()
        self._agents = {}

    def agent(self, name):
        if name not in self._agents:
            self._agents[name] = build_agent(name)
        return self._agents[name]

    def _chat(self, name, message):
        """استدعاء الوكيل بمهلة زمنية (CHAT_TIMEOUT_S) عبر thread منفصل."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.agent(name).chat, message)
            try:
                result = future.result(timeout=CHAT_TIMEOUT_S)
            except FutureTimeout:
                future.cancel()
                raise RuntimeError(
                    f"agent '{name}' timed out after {CHAT_TIMEOUT_S}s")
        return result if isinstance(result, str) else str(result)

    @staticmethod
    def _critic_notes(deep, raw):
        """تجميع ملاحظات الناقد (JSON أو نص خام) لتغذية reviser."""
        notes = []
        for key in ("notes", "suggestions", "style", "fluency", "accuracy"):
            v = deep.get(key)
            if isinstance(v, list):
                notes.extend(str(x) for x in v)
            elif isinstance(v, str) and v.strip():
                notes.append(v)
        return "\n".join(f"- {n}" for n in notes) or raw[-1500:]

    # ------------------------------------------------------------- memory --
    def save_state(self, key, value):
        """حفظ الحالة عبر ملف ذاكرة ASOST (نفس مخزن asost_memory tools)."""
        import os
        path = _memory_path()
        try:
            data = json.load(open(path, encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (FileNotFoundError, ValueError, OSError):
            data = {}
        data[key] = value
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    def load_state(self, key, default=None):
        import os
        path = _memory_path()
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return default
        val = data.get(key, default)
        if isinstance(val, (dict, list)):
            return val
        return val

    # ------------------------------------------------------------ pipeline --
    def translate_page(self, page_num, src_text, context=""):
        """دورة كاملة: ترجمة → نقد سريع → قرار قبول / نقد عميق.

        يعمل dict: {page, translation, light: {...}, deep?: {...},
                    decision: accepted|rejected|deep_reviewed}
        """
        ctx = context or self.load_state(f"page_{page_num}_context", "")
        if not src_text or not str(src_text).strip():
            raise ValueError("translate_page: src_text فارغ — رفض مبكر.")
        if len(str(src_text)) < 50:
            raise ValueError(
                f"translate_page: src_text أقصر من 50 حرفاً "
                f"({len(src_text)}) — رفض مبكر.")
        segments = _segment_source(src_text)
        print(f"[orchestrator] page {page_num}: translating ({len(src_text)} chars, "
              f"{len(segments)} segments)...")
        translated_segments = [self._chat(
            "translator",
            "Translate this complete segment to literary Arabic. Preserve every "
            "paragraph, dialogue line, number, protected name and image marker.\n\n"
            f"{segment}",
        ).strip() for segment in segments]
        translation = "\n\n".join(translated_segments)

        validation = _deterministic_checks(src_text, translation)
        decision = {"page": page_num, "translation": translation,
                    "segments": len(segments), "validation": validation,
                    "revision_rounds": 0}
        if not validation["passed"]:
            decision.update({"light": {}, "light_score": None,
                             "decision": "rejected"})
            print("[orchestrator] deterministic full-page gate → REJECTED")
            self.save_state(f"page_{page_num}_result",
                            {k: v for k, v in decision.items()
                             if k != "translation"})
            return decision

        print("[orchestrator] critic_light reviewing every complete segment...")
        light_reviews, light_scores = [], []
        for source_segment, translated_segment in zip(segments, translated_segments):
            raw = self._chat(
                "critic_light", "قيّم القطعة الكاملة التالية. " + JSON_ONLY_RULE
                + f"\n\nORIGINAL:\n{source_segment}\n\nTRANSLATION:\n{translated_segment}")
            review = _extract_json(raw) or {}
            light_reviews.append(review)
            found = _extract_score(review)
            if found is None:
                m = re.search(r'"?(?:overall_)?score"?\s*[:=]\s*([\d.]+)', raw)
                if m:
                    value = float(m.group(1))
                    found = int(round(value * 10 if value <= 10 else value))
            light_scores.append(found)
        light = light_reviews[0] if len(light_reviews) == 1 else {"segments": light_reviews}
        score = min(light_scores) if all(s is not None for s in light_scores) else None
        decision.update({"light": light, "light_score": score,
                         "segment_light_scores": light_scores})

        if score is not None and score >= ACCEPT_THRESHOLD:
            decision["decision"] = "accepted"
            print(f"[orchestrator] score={score} >= {ACCEPT_THRESHOLD} → ACCEPTED")
            self.save_state(f"page_{page_num}_result",
                            {k: v for k, v in decision.items()
                             if k != "translation"})
            return decision
        else:
            print(f"[orchestrator] score={score} < {ACCEPT_THRESHOLD} "
                  f"→ escalating to critic_deep...")

        # Map/reduce: no aggregate verdict can hide a bad tail segment.  The
        # reducer is deliberately the minimum score and requires every map
        # result to be parseable and above the threshold.
        print("[orchestrator] critic_deep reviewing every complete segment...")
        deep_reviews, deep_scores = [], []
        for source_segment, translated_segment in zip(segments, translated_segments):
            raw_d = self._chat(
                "critic_deep",
                "قيّم القطعة الكاملة التالية أدبياً. " + JSON_ONLY_RULE
                + f"\n\nORIGINAL:\n{source_segment}"
                  f"\n\nTRANSLATION:\n{translated_segment}")
            deep = _extract_json(raw_d) or {}
            deep_reviews.append(deep)
            deep_scores.append(_extract_score(deep))
        dscore = min(deep_scores) if all(
            item is not None for item in deep_scores) else None
        decision["deep"] = (deep_reviews[0] if len(deep_reviews) == 1
                            else {"segments": deep_reviews})
        decision["segment_deep_scores"] = deep_scores
        decision["deep_score"] = dscore
        if dscore is not None and dscore >= ACCEPT_THRESHOLD:
            decision["decision"] = "accepted"
            print(f"[orchestrator] all deep segment verdicts accepted ({dscore})")
        else:
            decision["decision"] = "best_effort"
            decision["best_score"] = max(
                [item for item in [score, dscore] if item is not None],
                default=None)
            print("[orchestrator] one or more deep segment verdicts failed "
                  "→ best_effort")

        # حفظ الحالة في الذاكرة التراكمية
        self.save_state(
            f"page_{page_num}_result",
            {k: v for k, v in decision.items() if k != "translation"},
        )
        return decision


if __name__ == "__main__":
    orch = ASOSTOrchestrator()
    for name in ["translator", "critic_light", "critic_deep",
                 "context_keeper", "book_adapter", "reviser"]:
        a = orch.agent(name)
        print(f"agent ready: {name} platform={a.asost_identity.get('platform')}")
