import fitz
d = fitz.open('/opt/data/projects/assost/tests/fullbook/full_book.pdf')
for i, p in enumerate(d):
    t = p.get_text()
    if 'التمهيد' in t:
        print('التمهيد on page:', i + 1)
    if 'ارتقاء المستوى' in t:
        print('ارتقاء on page:', i + 1)
print('p1 chars:', len(d[0].get_text().strip()))
print('total pages:', len(d))
