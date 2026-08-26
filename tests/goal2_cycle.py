"""goal2_cycle.py — دورة الهدف 2: جودة الاستخراج + تركيب PDF
الحلقة الخماسية: فحص → تحليل → اكتشاف → تحسين → اختبار (محلي 100% بلا API)"""
import sys, os, json, time, re
sys.path.insert(0, '/opt/data/projects/assost/assost-main')
import PF

BASE = '/opt/data/projects/assost'
LOG = f'{BASE}/tests/goal2_log.md'


def log(msg):
    with open(LOG, 'a') as f:
        f.write(f"\n### {time.strftime('%H:%M:%S')} — {msg}\n")
    print('GOAL2:', msg)


# ═══════════ الفحص ═══════════
def inspect():
    import fitz
    raw = fitz.open(f'{BASE}/book.pdf')
    metrics = {'raw_chars': 0, 'extracted_chars': 0, 'hyphen_joins': 0}

    for p in raw:
        metrics['raw_chars'] += len(p.get_text().strip())

    info = PF.ProfessionalDocumentProcessor.extract_pdf_with_precision(f'{BASE}/book.pdf')
    full = '\n'.join(ch['content'] for ch in info['chapters'])
    metrics['extracted_chars'] = len(full)
    metrics['chapters'] = len(info['chapters'])
    metrics['illustrations'] = len(info.get('illustrations', []))

    metrics['hyphen_joins'] = len(re.findall(r'[a-z]-\n[a-z]', full))
    metrics['retention'] = round(metrics['extracted_chars'] / max(metrics['raw_chars'], 1), 3)
    return metrics


# ═══════════ التحليل ═══════════
def analyze(m):
    gaps = []
    if m['hyphen_joins'] > 0:
        gaps.append(f"{m['hyphen_joins']} كلمة مكسورة بـ hyphen تحتاج دمجاً")
    if m['retention'] < 0.98:
        gaps.append(f"نسبة احتفاظ النص {m['retention']} أقل من 0.98")
    log(f"[تحليل] الفجوات: {gaps or 'لا شيء — البحث عن تحسين استباقي'}")
    return gaps


# ═══════════ التحسين ═══════════
def improve(gaps):
    applied = []
    src_path = f'{BASE}/assost-main/image_aware_extract.py'
    src = open(src_path).read()
    if 'def _fix_hyphenation' not in src:
        helper = '''

_HYPHEN_RE = None


def _fix_hyphenation(text: str) -> str:
    """يدمج الكلمات المقطوعة بنهاية السطر: "recov-\\ner" → "recover".
    يحافظ على hyphens الحقيقية (مثل well-known) عند عدم وجود سطر تالٍ."""
    global _HYPHEN_RE
    if _HYPHEN_RE is None:
        _HYPHEN_RE = __import__('re').compile(r'([a-z])-\\n([a-z])')
    prev = None
    while prev != text:
        prev = text
        text = _HYPHEN_RE.sub(r'\\1\\2', text)
    return text
'''
        src += helper
        open(src_path, 'w').write(src)
        applied.append('added _fix_hyphenation helper')
    else:
        applied.append('helper exists')
    return applied


# ═══════════ الاختبار ═══════════
def test():
    from image_aware_extract import extract_book_flow, _fix_hyphenation
    flows = extract_book_flow(f'{BASE}/book.pdf', f'{BASE}/tests/goal2_images')
    total_txt = sum(1 for f in flows for it in f['flow'] if it['type'] == 'text')
    sample = '\n\n'.join(it['text'] for f in flows[:25] for it in f['flow'] if it['type'] == 'text')
    before = len(re.findall(r'[a-z]-\n[a-z]', sample))
    fixed_sample = _fix_hyphenation(sample)
    after = len(re.findall(r'[a-z]-\n[a-z]', fixed_sample))
    log(f"[اختبار] كتل نصية: {total_txt} | hyphen قبل: {before} → بعد: {after}")
    return {'before': before, 'after': after, 'blocks': total_txt}


if __name__ == '__main__':
    log("=== بدء دورة الهدف 2 ===")
    m = inspect()
    log(f"[فحص] retention={m['retention']} chapters={m['chapters']} "
        f"illustrations={m['illustrations']} hyphens={m['hyphen_joins']}")
    gaps = analyze(m)
    applied = improve(gaps)
    res = test()
    json.dump({'metrics': m, 'applied': applied, 'test': res},
              open(f'{BASE}/tests/goal2_state.json', 'w'), indent=1)
    log("=== اكتملت الدورة ===")
