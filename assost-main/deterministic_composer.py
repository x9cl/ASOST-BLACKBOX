"""deterministic_composer.py — المؤلف الحتمي (v1): لا تخمين نصي إطلاقاً.
المبدأ: كل صفحة أصلية = وحدة مخرج مستقلة بنفس ترتيب عناصرها.
  • صفحة رسمة كاملة → صفحة صورة كاملة في نفس موضع التسلسل
  • صفحة نصية → نصها المترجم (من paged_translations.json لنفس رقم الصفحة)
  • لو احتوت صفحة نصية صوراً (mixed): العلامة تُدرج بعد نسبة الفقرات
    التي تسبق الصورة في الأصل (y-order) — حتمي، لا بحث نصي.
الأحجام: من bbox الأصلي نسبةً لعرض صفحة PDF (ليست ثابتة 4.5in).
المخرجات: pages_flow موحّد يغذي arabic_pdf.build_pdf و compose_docx.build_docx
"""
import os, sys, json
import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from image_aware_extract import extract_page_flow

IMG_MARK = '[IMG:%s|%s]'


def analyze_pages(pdf_path, images_dir):
    """وحدات الصفحات: kind + flow + أحجام هندسية."""
    doc = fitz.open(pdf_path)
    units = []
    for pi in range(len(doc)):
        page = doc[pi]
        pw = page.rect.width
        flow = extract_page_flow(pdf_path, pi, images_dir)['flow']
        imgs = [i for i in flow if i['type'] == 'image']
        txts = [i for i in flow if i['type'] == 'text']
        total_txt = sum(len(t['text']) for t in txts)
        has_fullpage = any(i.get('class') == 'full_page' and i['w'] >= 300 for i in imgs)
        if has_fullpage and total_txt < 100:
            kind = 'illustration'
        elif total_txt >= 40:
            kind = 'text'
        elif imgs:
            kind = 'illustration'
        else:
            kind = 'empty'
        units.append({'page': pi + 1, 'kind': kind, 'flow': flow,
                      'page_width': pw, 'n_text': len(txts)})
    doc.close()
    return units


def _insert_marker_by_ratio(translated_text, n_before, n_total, name, cls):
    """إدراج العلامة بعد الفقرة رقم n_before من أصل n_total (حتمي بالفهرس)."""
    paras = [p for p in translated_text.split('\n\n') if p.strip()]
    if not paras:
        return IMG_MARK % (name, cls)
    # موضع نسبي مطابق للأصل؛ إن كانت الفقرات أقل ندرج في النهاية/البداية
    idx = min(len(paras), max(0, round(n_before / max(1, n_total) * len(paras))))
    paras.insert(idx, IMG_MARK % (name, cls))
    return '\n\n'.join(paras)


def build_pages_flow(pdf_path, images_dir, translations, skip_cover=True):
    """translations: {str(page_num): translated_text} — من paged_translations.json.
    يعيد (pages_flow, report) — كل عنصر صفحة بترتيب الأصل تماماً."""
    units = analyze_pages(pdf_path, images_dir)
    doc = fitz.open(pdf_path)
    pages_flow, report = [], {'pages': 0, 'illustration_pages': 0,
                              'inline_images': 0, 'missing_translations': [],
                              'sizes': []}
    for u in units:
        if u['kind'] == 'empty':
            continue
        if skip_cover and u['page'] == 1 and u['kind'] == 'illustration':
            continue  # الغلاف = رسمة كاملة في الصفحة 1 فقط
        report['pages'] += 1
        if u['kind'] == 'illustration':
            big = max((i for i in u['flow'] if i['type'] == 'image'),
                      key=lambda i: i['w'] * i['h'])
            name = os.path.basename(big['path'])
            # حجم كامل الصفحة: نسبة bbox لعرض صفحة الأصل
            frac = min(1.0, big['w'] / u['page_width'])
            pages_flow.append({'kind': 'illustration', 'image': name,
                               'width_frac': round(frac, 3),
                               'src_page': u['page'],
                               'images': {name: big['path']},
                               'text_with_markers': IMG_MARK % (name, 'full_page')})
            report['illustration_pages'] += 1
            report['sizes'].append({'img': name, 'frac': round(frac, 3)})
            continue
        # صفحة نصية — ربما تحتوي صوراً داخلية (mixed)
        t = translations.get(str(u['page']), '')
        if not t:
            report['missing_translations'].append(u['page'])
        txt_items = [i for i in u['flow'] if i['type'] == 'text']
        img_items = sorted([i for i in u['flow'] if i['type'] == 'image'],
                           key=lambda i: i['y'])
        markers = {}
        imaps = {}
        n_total = len(txt_items)
        for it in img_items:
            name = os.path.basename(it['path'])
            n_before = sum(1 for x in txt_items if x['y'] < it['y'])
            markers.setdefault(
                _insert_marker_by_ratio(t or '', n_before, n_total,
                                        name, it.get('class', 'illustration')), None)
            imaps[name] = it['path']
            frac = min(1.0, it['w'] / u['page_width'])
            report['sizes'].append({'img': name, 'frac': round(frac, 3)})
            report['inline_images'] += 1
        body = t
        for m in markers:
            body = m if not body else body  # mixed نادر — يُدمج أدناه
        if img_items:
            # دمج: أعِد بناء النص مع العلامات بمواضعها النسبية
            paras = [p for p in (t or '').split('\n\n') if p.strip()]
            out, inserted = [], 0
            for k, para in enumerate(paras):
                out.append(para)
                for it in img_items:
                    n_before = sum(1 for x in txt_items if x['y'] < it['y'])
                    ratio_pos = round(n_before / max(1, n_total) * len(paras))
                    if k + 1 == ratio_pos:
                        nm = os.path.basename(it['path'])
                        fr = min(1.0, it['w'] / u['page_width'])
                        out.append(IMG_MARK % (nm, f'{it.get("class","illustration")}|w{fr}'))
                        inserted += 1
            for it in img_items:  # أي علامة لم تُدرج → النهاية
                nm = os.path.basename(it['path'])
                if not any(nm in p for p in out):
                    fr = min(1.0, it['w'] / u['page_width'])
                    out.append(IMG_MARK % (nm, f'{it.get("class","illustration")}|w{fr}'))
            body = '\n\n'.join(out)
            pages_flow.append({'kind': 'text', 'text_with_markers': body,
                               'images': imaps, 'src_page': u['page']})
        else:
            pages_flow.append({'kind': 'text', 'text_with_markers': t or '',
                               'images': {}, 'src_page': u['page']})
    doc.close()
    return pages_flow, report


if __name__ == '__main__':
    BASE = '/opt/data/projects/assost'
    tr = json.load(open(f'{BASE}/tests/fullbook/paged_translations.json'))
    pf, rep = build_pages_flow(f'{BASE}/book.pdf', f'{BASE}/tests/fullbook/images',
                               tr)
    json.dump(rep, open(f'{BASE}/tests/fullbook/composer_report.json',
                        'w'), ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print('units:', len(pf))
    for p in pf[:12]:
        print(p['kind'], p.get('src_page'), (p.get('image') or p['text_with_markers'][:40].replace('\n', ' ')))
