import fitz
d = fitz.open('book.pdf')
for pi in [0, 3]:
    p = d[pi]
    print(f'--- page {pi+1} ---')
    for i in p.get_image_info(xrefs=True):
        b = i['bbox']
        print(f'xref={i.get("xref")} size={b[2]-b[0]:.0f}x{b[3]-b[1]:.0f}')
    for img in p.get_images(full=True):
        pix = fitz.Pixmap(d, img[0])
        print('  get_images xref', img[0], pix.width, 'x', pix.height)
