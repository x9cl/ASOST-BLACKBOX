"""orchestrator.py — مدير وكلاء ASOST الدائمين.

يدير دورة الترجمة: المترجم → الناقد السريع → (الناقد العميق عند الحاجة)
مع حفظ/تحميل الحالة عبر أدوات asost_memory.
"""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from agent_runner import build_agent, ensure_hermes_home  # noqa: F401

ACCEPT_THRESHOLD = 85
CHAT_TIMEOUT_S = 300


JSON_ONLY_RULE = ('أعد إجابتك كـ JSON واحد فقط بهذا الشكل: '
                  '{"score": <0-100>, "notes": [...]}. لا نص قبل أو بعد.')

MAX_REVISION_ROUNDS = 3
_MEMORY_LOCK = threading.RLock()


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

    def __init__(self, book_id, run_id, agent_instance_id):
        ensure_hermes_home()
        self._agents = {}
        if any(value is None or not str(value).strip()
               for value in (book_id, run_id, agent_instance_id)):
            raise ValueError("book_id, run_id and agent_instance_id must not be empty")
        self.book_id = str(book_id)
        self.run_id = str(run_id)
        self.agent_instance_id = str(agent_instance_id)
        self.memory_namespace = f"asost:{self.book_id}:{self.run_id}"

    def agent(self, name):
        if name not in self._agents:
            self._agents[name] = build_agent(
                name, self.book_id, self.run_id, self.agent_instance_id)
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
        path = _memory_path()
        with _MEMORY_LOCK:
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            except (FileNotFoundError, ValueError, OSError):
                data = {}
            namespace = data.setdefault(self.memory_namespace, {})
            namespace[key] = value
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    def load_state(self, key, default=None):
        path = _memory_path()
        with _MEMORY_LOCK:
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, ValueError, OSError):
                return default
            val = data.get(self.memory_namespace, {}).get(key, default)
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
        print(f"[orchestrator] page {page_num}: translating ({len(src_text)} chars)...")
        translation = self._chat(
            "translator",
            f"Translate to literary Arabic:\n\n{src_text}",
        ).strip()

        print("[orchestrator] critic_light reviewing...")
        raw = self._chat(
            "critic_light",
            "قيّم هذه الترجمة. " + JSON_ONLY_RULE + "\n\n"
            f"ORIGINAL:\n{src_text[:2000]}\n\nTRANSLATION:\n{translation[:3000]}",
        )
        light = _extract_json(raw) or {}
        score = _extract_score(light)
        if score is None:
            # fallback: أي "score" رقمي داخل النص الخام
            m = re.search(r'"?(?:overall_)?score"?\s*[:=]\s*([\d.]+)', raw)
            if m:
                v = float(m.group(1))
                score = int(round(v * 10 if v <= 10 else v))

        decision = {"page": page_num, "translation": translation,
                    "book_id": self.book_id, "run_id": self.run_id,
                    "agent_instance_id": self.agent_instance_id,
                    "memory_namespace": self.memory_namespace,
                    "light": light, "light_score": score}

        if score is not None and score >= ACCEPT_THRESHOLD:
            decision["decision"] = "accepted"
            print(f"[orchestrator] score={score} >= {ACCEPT_THRESHOLD} → ACCEPTED")
        else:
            print(f"[orchestrator] score={score} < {ACCEPT_THRESHOLD} "
                  f"→ escalating to critic_deep...")

        # ------------------------------------------------- deep review loop --
        decision["revision_rounds"] = 0
        round_scores = [score] if score is not None else []
        best = {"translation": translation, "score": score if score is not None else -1}
        rounds = 0
        while True:
            raw_d = self._chat(
                "critic_deep",
                "قيّم هذه الترجمة أدبياً. " + JSON_ONLY_RULE + "\n\n"
                f"ORIGINAL:\n{src_text[:2000]}\n\nTRANSLATION:\n{decision['translation'][:3000]}",
            )
            deep = _extract_json(raw_d) or {}
            decision["deep"] = deep
            dscore = _extract_score(deep)
            if dscore is not None:
                decision["deep_score"] = dscore
                round_scores.append(dscore)
                if dscore > best["score"]:
                    best = {"translation": decision["translation"], "score": dscore}
            if dscore is not None and dscore >= ACCEPT_THRESHOLD:
                decision["decision"] = "accepted"
                print(f"[orchestrator] deep verdict → accepted ({dscore})")
                break
            # rejected (أو بلا درجة قابلة للاستخراج) → جولة مراجعة عبر reviser
            if rounds >= MAX_REVISION_ROUNDS:
                decision["translation"] = best["translation"]
                decision["best_score"] = max(round_scores) if round_scores else None
                decision["decision"] = "best_effort"
                print(f"[orchestrator] max revision rounds ({MAX_REVISION_ROUNDS}) "
                      f"reached → best_effort (best score={decision['best_score']})")
                break
            rounds += 1
            decision["revision_rounds"] = rounds
            notes = self._critic_notes(deep, raw_d)
            print(f"[orchestrator] rejected (deep score={dscore}) → "
                  f"revision round {rounds}/{MAX_REVISION_ROUNDS} via reviser...")
            revised = self._chat(
                "reviser",
                "صحّح المسودة الأدبية التالية حلّاً كل ملاحظة من ملاحظات الناقد "
                "بدون تغيير المعنى. أعد النص العربي المصحح فقط بدون أي شرح.\n\n"
                f"ORIGINAL:\n{src_text[:2000]}\n\n"
                f"DRAFT:\n{decision['translation'][:3000]}\n\n"
                f"CRITIC NOTES:\n{notes}",
            ).strip()
            if revised:
                decision["translation"] = revised
            # إعادة التقييم: ناقد خفيف ثم عميق إن لزم
            print("[orchestrator] critic_light re-reviewing revised draft...")
            raw_l2 = self._chat(
                "critic_light",
                "قيّم هذه الترجمة. " + JSON_ONLY_RULE + "\n\n"
                f"ORIGINAL:\n{src_text[:2000]}\n\n"
                f"TRANSLATION:\n{decision['translation'][:3000]}",
            )
            light2 = _extract_json(raw_l2) or {}
            s2 = _extract_score(light2)
            decision["light"] = light2
            if s2 is not None:
                round_scores.append(s2)
                if s2 > best["score"]:
                    best = {"translation": decision["translation"], "score": s2}
                if s2 >= ACCEPT_THRESHOLD:
                    decision["light_score"] = s2
                    decision["decision"] = "accepted"
                    print(f"[orchestrator] revised draft accepted by light critic ({s2})")
                    break
            print(f"[orchestrator] light re-review score={s2} < {ACCEPT_THRESHOLD} "
                  f"→ back to critic_deep")

        # حفظ الحالة في الذاكرة التراكمية
        self.save_state(
            f"page_{page_num}_result",
            {k: v for k, v in decision.items() if k != "translation"},
        )
        return decision


if __name__ == "__main__":
    orch = ASOSTOrchestrator("manual-book", "manual-run", "manual-supervisor")
    for name in ["translator", "critic_light", "critic_deep",
                 "context_keeper", "book_adapter", "reviser"]:
        a = orch.agent(name)
        print(f"agent ready: {name} platform={a.asost_identity.get('platform')}")
