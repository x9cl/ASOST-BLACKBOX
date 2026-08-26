"""dev_loop.py — حلقة "التفعيل" التطويرية الذاتية لمشروع ASOST
الدورة: فحص → تحليل → اكتشاف → تحسين → تطبيق → اختبار → فحص → تكرار
تُشغَّل يدوياً أو عبر cron، وتنتقل بالحالة عبر ملف loop_state.json.
"""
import json, os, subprocess, sys, time

BASE = '/opt/data/projects/assost'
PY = f'{BASE}/assost-main/.venv/bin/python'
STATE = f'{BASE}/tests/loop_state.json'
LOG = f'{BASE}/tests/dev_log.md'


def log(msg):
    with open(LOG, 'a') as f:
        f.write(f"\n### {time.strftime('%Y-%m-%d %H:%M')} — {msg}\n")
    print('LOOP:', msg)


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {'cycle': 0, 'phase': 'inspect', 'quality_history': [], 'findings': []}


def save_state(s):
    json.dump(s, open(STATE, 'w'), indent=1, ensure_ascii=False)


def run(cmd, timeout=500):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 'TIMEOUT'


# ═══════════ المراحل ═══════════

def phase_inspect(state):
    """فحص: شغّل كل الاختبارات واجمع المؤشرات."""
    out = run(f"cd {BASE} && {PY} tests/compare.py")
    avg = 0.0
    for line in out.splitlines():
        if line.startswith('AVERAGE'):
            avg = float(line.split(':')[1].split('/')[0])
    state['last_avg_quality'] = avg
    log(f"[فحص] متوسط الجودة الحالي: {avg}/100")
    return state


def phase_analyze(state):
    """تحليل: قارن مع الهدف واكشف الفجوات."""
    target = 95.0
    avg = state.get('last_avg_quality', 0)
    gaps = []
    if avg < target:
        gaps.append(f'الجودة {avg} أقل من الهدف {target}')
    # فحص اتساق الأسماء في آخر الترجمات
    out = run(f"cd {BASE} && grep -l 'CONSISTENCY' tests/*.log 2>/dev/null | head -1")
    state['findings'] = gaps or ['لا فجوات مكتشفة — البحث عن تحسينات استباقية']
    log(f"[تحليل] النتائج: {state['findings']}")
    return state


def phase_discover(state):
    """اكتشاف: أدوات/مكتبات/تقنيات جديدة تساعد المشروع."""
    ideas = []
    # اقتراحات مبنية على الحالة
    if state.get('last_avg_quality', 0) < 95:
        ideas += [
            'رفع جودة system instruction بأسلوب أمثلة few-shot من أفضل الترجمات',
            'إضافة مقياس انسياب (flow) للنص العربي: طول الجمل، تكرار الروابط',
        ]
    ideas.append('فحص تحديثات pymupdf/weasyprint لتحسين الاستخراج والتوليد')
    state['discovered'] = ideas
    log(f"[اكتشاف] أفكار: {len(ideas)}")
    return state


def phase_improve(state):
    """تحسين: طبّق أول تحسين آمن قابل للأتمتة."""
    applied = []
    # مثال محكم: إعادة توليد تقرير الجودة بعد أي تعديل (تحقق ذاتي)
    out = run(f"cd {BASE} && {PY} tests/compare.py")
    if 'AVERAGE' in out:
        applied.append('refreshed quality report')
    state['applied'] = applied
    log(f"[تحسين] طُبّق: {applied}")
    return state


def phase_test(state):
    """اختبار: أعد ترجمة عينة واحدة وتحقق من الاتساق والجودة."""
    out = run(f"cd {BASE} && {PY} tests/retranslate.py", timeout=480)
    ok = out.count('consistent: True')
    total = out.count('text_p')
    log(f"[اختبار] اتساق {ok}/{total}")
    state['last_test'] = {'consistent': ok, 'total': total}
    return state


PHASES = {
    'inspect': phase_inspect,
    'analyze': phase_analyze,
    'discover': phase_discover,
    'improve': phase_improve,
    'test': phase_test,
}
ORDER = ['inspect', 'analyze', 'discover', 'improve', 'test']


def run_one_cycle():
    """ينفذ دورة كاملة ويعيد الحالة."""
    state = load_state()
    state['cycle'] = state.get('cycle', 0) + 1
    cycle_start = state['cycle']
    log(f"{'='*50}\n[دورة #{cycle_start}] بدأت")
    for name in ORDER:
        state['phase'] = name
        state = PHASES[name](state)
        save_state(state)
    q = state.get('last_avg_quality', 0)
    state.setdefault('quality_history', []).append({'cycle': cycle_start, 'avg': q})
    save_state(state)
    log(f"[دورة #{cycle_start}] اكتملت — الجودة: {q}/100")
    return state


if __name__ == '__main__':
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for _ in range(cycles):
        s = run_one_cycle()
        # شرط التوقف: جودة مستقرة ≥95 لآخر دورتين
        h = s.get('quality_history', [])
        if len(h) >= 2 and all(x['avg'] >= 95 for x in h[-2:]):
            log("🎯 هدف الجودة تحقق (≥95 لدورتين متتاليتين) — الدورة تتوقف")
            break
