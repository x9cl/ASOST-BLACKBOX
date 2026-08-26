"""fidelity_v3 — مقارنة بالتطابق البصري (hash) بدل أرقام الصفحات:
أرقام الصفحات تختلف بطبيعتها بين الأصل والترجمة (عناوين/فهرس مضافة).
المعيار الصحيح: كل صورة أصلية موجودة في الناتج، مرة واحدة، بالترتيب."""
import fitz, hashlib, json

def imghash(doc, page):
    for inf in doc[page].get_image_info(xrefs=True):
        b = inf['bbox']
        if b[2] - b[0] >= 100 and b[3] - b[1] >= 100:
            pix = fitz.Pixmap(doc, inf['xref'])
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            return hashlib.md5(pix.tobytes('png')).hexdigest()[:12]
    return None

orig = fitz.open('/opt/data/projects/assost/book.pdf')
new = fitz.open('/opt/data/projects/assost/tests/fullbook/full_book.pdf')

orig_seq = []
for pi in range(len(orig)):
    h = imghash(orig, pi)
    if h:
        orig_seq.append((h, pi + 1))

new_hashes = {}
for pi in range(len(new)):
    h = imghash(new, pi)
    if h:
        new_hashes.setdefault(h, []).append(pi + 1)

results = []
for h, op in orig_seq:
    pages = new_hashes.get(h, [])
    results.append({
        'orig_page': op,
        'present': bool(pages),
        'output_pages': pages,
        'exactly_once': len(pages) == 1,
    })

report = {
    'original_illustrations': len(orig_seq),
    'all_present': all(r['present'] for r in results),
    'no_duplicates': all(r['exactly_once'] for r in results),
    'details': results,
}
json.dump(report, open('/opt/data/projects/assost/tests/fullbook/fidelity_report.json', 'w'),
          indent=1, ensure_ascii=False)
print(json.dumps(report, indent=1, ensure_ascii=False))
