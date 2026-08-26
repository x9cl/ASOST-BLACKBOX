import fitz, re, sys
sys.path.insert(0, '/opt/data/projects/assost/assost-main')

# === EXTRACTION AUDIT ===
from image_aware_extract import extract_book_flow, _fix_hyphenation
flows = extract_book_flow('/opt/data/projects/assost/book.pdf', '/opt/data/projects/assost/tests/goal2_images')
txt_blocks = [it['text'] for f in flows for it in f['flow'] if it['type'] == 'text']
sample = chr(10).join(txt_blocks)
h_raw = len(re.findall(r'[a-z]-\n[a-z]', sample))
h_fixed = len(re.findall(r'[a-z]-\n[a-z]', _fix_hyphenation(sample)))
imgs = sum(1 for f in flows for it in f['flow'] if it['type'] == 'image')
print(f'EXTRACTION: blocks={len(txt_blocks)} hyphen_raw={h_raw} hyphen_fixed={h_fixed} images={imgs}')

# === COMPOSITION AUDIT ===
d = fitz.open('/opt/data/projects/assost/tests/fullbook/full_book.pdf')
violations = []
for i in range(1, len(d)):
    words = d[i].get_text('words')
    if not words:
        continue
    xs = [w[0] for w in words]
    xe = [w[2] for w in words]
    if min(xs) < 40 or max(xe) > 385:
        violations.append(i + 1)
full = ''.join(p.get_text() for p in d)
clean = open('/opt/data/projects/assost/tests/fullbook/full_book_ar.txt.clean').read()
checks = {
    'cover_clean_p1_empty': len(d[0].get_text().strip()) == 0,
    'title_page_p2': 'Death March' in full,
    'toc_page_p3': 'فهرس المحتويات' in full,
    'ch1_heading': 'التمهيد' in full,
    'ch2_heading': 'ارتقاء المستوى' in full,
    'no_fake_seams': len(re.findall(chr(10) + '---' + chr(10), clean)) == 0,
    'no_margin_violations': not violations,
}
print('COMPOSITION:')
for k, v in checks.items():
    print(f'  {k}: {"PASS" if v else "FAIL"}')
ok = all(checks.values()) and h_fixed == 0
print(f'ALL PASS: {ok}')
