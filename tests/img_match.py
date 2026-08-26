import fitz, hashlib

def imghash(doc, page):
    infos = doc[page].get_image_info(xrefs=True)
    for inf in infos:
        b = inf['bbox']
        if b[2] - b[0] >= 100 and b[3] - b[1] >= 100:
            pix = fitz.Pixmap(doc, inf['xref'])
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            data = pix.tobytes('png')
            return hashlib.md5(data).hexdigest()[:12]
    return None

orig = fitz.open('/opt/data/projects/assost/book.pdf')
new = fitz.open('/opt/data/projects/assost/tests/fullbook/full_book.pdf')

orig_h = {}
for pi in [0, 1, 2, 3, 4, 5, 23]:
    h = imghash(orig, pi)
    if h:
        orig_h[h] = f'orig p{pi+1}'

print('output images -> matched original:')
for pi in [0, 2, 3, 4, 5, 6, 7, 30]:
    h = imghash(new, pi)
    src = orig_h.get(h, 'NO MATCH')
    print(f'  out p{pi+1} [{h}] <- {src}')
