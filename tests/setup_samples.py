"""تثبيت عينات الاختبار المرجعية من book.pdf (Death March Vol.01)."""
import fitz, json, os

BASE = '/opt/data/projects/assost'
SAMPLES = f'{BASE}/tests/samples'
os.makedirs(f'{SAMPLES}/images', exist_ok=True)

doc = fitz.open(f'{BASE}/book.pdf')

# عينات نصية صعبة + مركبة (نص+صور)
TEXT_SAMPLES = [19, 26, 29]      # صفحات 20، 27، 30
MIXED_SAMPLES = [19, 6]          # صفحة 20 (4 صور) وصفحة 7 (نص+صورة)

manifest = {"text": [], "mixed": []}

for idx in TEXT_SAMPLES:
    p = doc[idx]
    text = p.get_text().strip()
    name = f'text_p{idx+1}'
    open(f'{SAMPLES}/{name}.txt', 'w').write(text)
    manifest["text"].append({"name": name, "page": idx+1, "chars": len(text)})
    print(name, len(text), 'chars')

for idx in MIXED_SAMPLES:
    p = doc[idx]
    text = p.get_text().strip()
    name = f'mixed_p{idx+1}'
    open(f'{SAMPLES}/{name}.txt', 'w').write(text)
    imgs = []
    for j, img in enumerate(p.get_images(full=True)):
        xref = img[0]
        pix = fitz.Pixmap(doc, xref)
        if pix.n - pix.alpha > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        ipath = f'{SAMPLES}/images/{name}_img{j}.png'
        pix.save(ipath)
        imgs.append({"path": ipath, "w": pix.width, "h": pix.height})
        pix = None
    # خريطة تدفق: مواقع الصور على الصفحة
    flow = []
    for info in p.get_image_info():
        flow.append({"bbox": info["bbox"], "y": info["bbox"][1]})
    flow.sort(key=lambda x: x["y"])
    manifest["mixed"].append({"name": name, "page": idx+1, "chars": len(text),
                              "images": imgs, "flow": flow})
    print(name, len(text), 'chars,', len(imgs), 'images')

json.dump(manifest, open(f'{SAMPLES}/manifest.json', 'w'), indent=2, ensure_ascii=False)
print('MANIFEST SAVED')
