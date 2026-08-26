"""أداة المقارنة الآلية: تقيس جودة الترجمة مقابل النص الأصلي.
مقاييس: اكتمال الأرقام والأسماء، نسبة الطول، بقايا إنجليزية، تشكيل عربي، أرقام محرفة."""
import re, json, sys, os

def arabic_ratio(text):
    ar = len(re.findall(r'[\u0600-\u06FF]', text))
    return ar / max(len(text), 1)

def leftover_english_words(text):
    # كلمات لاتينية بطول >3 لم تُترجم (باستثناء أسماء علم شائعة)
    known = {'AR', 'AI', 'NPC', 'SAT', 'MMO'}
    words = re.findall(r'\b[A-Za-z]{4,}\b', text)
    return [w for w in words if w not in known]

AR_NUM_WORDS = {'صفر': '0', 'واحد': '1', 'اثنان': '2', 'ثلاث': '3', 'ثلاثة': '3',
    'ثلاثمئة': '300', 'ثلاثمائة': '300', 'أربعمائة': '400', 'خمسمائة': '500', 'أربعة': '4', 'خمسة': '5', 'ستة': '6', 'سبعة': '7',
    'ثمانية': '8', 'تسعة': '9', 'عشرة': '10', 'عشرون': '20', 'ثلاثون': '30',
    'مئة': '100', 'مائة': '100', 'ألف': '1000', 'آلاف': '1000',
    'مليون': '1000000', 'ملايين': '1000000'}

def _arabic_number_values(text):
    """يستخرج قيم الأرقام المكتوبة: كلمات عربية + أرقام شرية ٠-٩."""
    vals = []
    east = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    for w in re.findall(r'[\u0600-\u06FF]+', text):
        # جرّد أدوات الربط (و، ف، ب، ل) الملتصقة بالبداية
        stripped = w
        while stripped and stripped not in AR_NUM_WORDS and len(stripped) > 3:
            if stripped[0] in 'وفبل':
                stripped = stripped[1:]
            else:
                break
        if stripped in AR_NUM_WORDS:
            vals.append(AR_NUM_WORDS[stripped])
        elif w in AR_NUM_WORDS:
            vals.append(AR_NUM_WORDS[w])
        t = w.translate(east)
        m = re.search(r'\d+', t)
        if m and any(c in '0123456789' for c in t):
            vals.append(m.group())
    return vals

def number_preservation(src, dst):
    """يقبل: نفس الرقم، أو رقماً شرقياً، أو كتابته ككلمة عربية (أسلوب أدبي سليم)."""
    src_nums = re.findall(r'\d+', src)
    if not src_nums:
        return 1.0
    vals = _arabic_number_values(dst)
    dst_candidates = set(re.findall(r'\d+', dst)) | set(vals)
    # تركيبات مجموع الأرقام المتتالية (ثلاثمئة + ثلاثة = 303)
    for i in range(len(vals)):
        acc = 0
        for j in range(i, min(i + 4, len(vals))):
            try:
                acc += int(vals[j])
            except ValueError:
                break
            if acc:
                dst_candidates.add(str(acc))
    match = sum(1 for n in src_nums if n in dst_candidates)
    return match / len(src_nums)

def length_ratio(src, dst):
    # الترجمة العربية الصحية: 60%-130% من طول المصدر
    r = len(dst) / max(len(src), 1)
    return round(r, 2), 1.0 if 0.6 <= r <= 1.3 else 0.0

def dialogue_preservation(src, dst):
    src_q = len(re.findall(r'["\u201c\u201d]', src)) // 2
    dst_q = len(re.findall(r'["\u00ab\u00bb"]', dst)) // 2
    if src_q == 0: return 1.0
    return min(dst_q / src_q, 1.0)

def paragraph_alignment(src, dst):
    sp = len([p for p in src.split('\n\n') if p.strip()])
    dp = len([p for p in dst.split('\n\n') if p.strip()])
    if sp == 0: return 1.0
    return 1.0 - min(abs(sp - dp) / sp, 1.0)

def compare(src_path, dst_path):
    src = open(src_path).read()
    dst = open(dst_path).read()
    lr, lr_ok = length_ratio(src, dst)
    metrics = {
        "arabic_ratio": round(arabic_ratio(dst), 3),
        "leftover_english": leftover_english_words(dst)[:10],
        "number_preservation": round(number_preservation(src, dst), 2),
        "length_ratio": lr,
        "dialogue_preservation": round(dialogue_preservation(src, dst), 2),
        "paragraph_alignment": round(paragraph_alignment(src, dst), 2),
    }
    score = (
        (metrics["arabic_ratio"] >= 0.7) * 20 +
        (len(metrics["leftover_english"]) == 0) * 15 +
        metrics["number_preservation"] * 20 +
        lr_ok * 20 +
        metrics["dialogue_preservation"] * 10 +
        metrics["paragraph_alignment"] * 15
    )
    metrics["score_100"] = round(score)
    return metrics

if __name__ == '__main__':
    base = sys.argv[1] if len(sys.argv) > 1 else '/opt/data/projects/assost/tests/baseline'
    report = {}
    for f in sorted(os.listdir(base)):
        if f.endswith('_cleaned_src.txt'):
            name = f.replace('_cleaned_src.txt', '')
            dst = f'{base}/{name}_ar.txt'
            if os.path.exists(dst):
                report[name] = compare(f'{base}/{f}', dst)
    json.dump(report, open(f'{base}/quality_report.json', 'w'), indent=2, ensure_ascii=False)
    avg = sum(m['score_100'] for m in report.values()) / max(len(report), 1)
    for k, v in report.items():
        print(f"{k}: score={v['score_100']} ar={v['arabic_ratio']} en_left={len(v['leftover_english'])} nums={v['number_preservation']} paras={v['paragraph_alignment']}")
    print(f"AVERAGE SCORE: {avg:.1f}/100")
