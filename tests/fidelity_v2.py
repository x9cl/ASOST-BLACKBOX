import fitz, json

MEANINGFUL_MIN = 100

orig = fitz.open('/opt/data/projects/assost/book.pdf')
new = fitz.open('/opt/data/projects/assost/tests/fullbook/full_book.pdf')

def meaningful_pages(doc):
    out = []
    for i, p in enumerate(doc):
        for info in p.get_image_info():
            b = info['bbox']
            w, h = b[2] - b[0], b[3] - b[1]
            if w >= MEANINGFUL_MIN and h >= MEANINGFUL_MIN:
                out.append(i + 1)
                break
    return out

o = meaningful_pages(orig)
n = meaningful_pages(new)
report = {
    'meaningful_illustration_pages_original': o,
    'meaningful_illustration_pages_output': n,
    'all_present': set(o).issubset(set(n)),
}
json.dump(report, open('/opt/data/projects/assost/tests/fullbook/fidelity_report.json', 'w'), indent=1)
print(json.dumps(report, indent=1))
