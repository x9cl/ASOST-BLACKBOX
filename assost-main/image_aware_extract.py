"""المرحلة 1 (منقّحة): استخراج واعٍ بالصور — image_aware_extract.py
يبني خريطة تدفق للصفحة: نصوص وصور بترتيبها الرأسي.
يصنّف الصور: illustrations كاملة (تُحفظ وتُدرج) vs رموز/زخارف صغيرة (تُهمل بذكاء)."""
from typing import Dict, Any, List
import os

# الحد الأدنى لحجم صورة تُعتبر "رسمة حقيقية" (نقاط صفحة، وليس رمزاً)
MIN_ILLUSTRATION_W = 100
MIN_ILLUSTRATION_H = 100
MIN_COVER_W = 300


def _classify_image(w: float, h: float) -> str:
    if w >= MIN_COVER_W and h >= MIN_COVER_W:
        return "full_page"      # غلاف/رسمة كاملة الصفحة
    if w >= MIN_ILLUSTRATION_W and h >= MIN_ILLUSTRATION_W:
        return "illustration"   # رسمة وسطية
    return "decoration"         # رموز SFX/زخارف — نتجاهلها في التركيب


def extract_page_flow(pdf_path: str, page_index: int, images_dir: str,
                      keep_decorations: bool = False) -> Dict[str, Any]:
    """يستخرج تدفق الصفحة كاملاً: نصوص وصور بترتيبها الرأسي الأصلي.

    flow items:
      {"type":"text","text":...,"y":...}
      {"type":"image","path":...,"y":...,"w":...,"h":...,"class":...}
    text_with_markers: نص مدموج مع [IMG:file] في مواضع الرسمات الحقيقية فقط.
    """
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    os.makedirs(images_dir, exist_ok=True)
    flow: List[Dict[str, Any]] = []

    # 1) بلوكات النص (type=0)
    for blk in raw.get("blocks", []):
        if blk.get("type") != 0:
            continue
        lines = []
        for ln in blk.get("lines", []):
            line = "".join(s.get("text", "") for s in ln.get("spans", []))
            if line.strip():
                lines.append(line.strip())
        text = "\n".join(lines).strip()
        if not text:
            continue
        y = blk.get("bbox", [0, 0, 0, 0])[1]
        flow.append({"type": "text", "text": text, "y": y})

    # 2) الصور — مع التصنيف الذكي
    saved: Dict[int, str] = {}
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref", 0)
        bbox = info.get("bbox", [0, 0, 0, 0])
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        cls = _classify_image(w, h)
        if cls == "decoration" and not keep_decorations:
            continue
        ipath = saved.get(xref)
        if not ipath and xref > 0:
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                ipath = os.path.join(images_dir, f"p{page_index+1}_x{xref}.png")
                pix.save(ipath)
                pix = None
                saved[xref] = ipath
            except Exception:
                ipath = None
        if ipath:
            flow.append({"type": "image", "path": ipath, "y": bbox[1],
                         "w": round(w), "h": round(h), "class": cls})

    flow.sort(key=lambda x: x["y"])
    parts = []
    for item in flow:
        if item["type"] == "text":
            parts.append(item["text"])
        else:
            parts.append(f"[IMG:{os.path.basename(item['path'])}|{item['class']}]")
    doc.close()
    return {"flow": flow, "text_with_markers": "\n\n".join(parts)}


def extract_book_flow(pdf_path: str, images_dir: str) -> List[Dict[str, Any]]:
    """خريطة تدفق الكتاب كاملاً — صفحة بصفحة."""
    import fitz
    doc = fitz.open(pdf_path)
    n = len(doc)
    doc.close()
    return [extract_page_flow(pdf_path, i, images_dir) for i in range(n)]


_HYPHEN_RE = None


def _fix_hyphenation(text: str) -> str:
    """يدمج الكلمات المقطوعة بنهاية السطر: "recov-\ner" → "recover".
    يحافظ على hyphens الحقيقية (مثل well-known) عند عدم وجود سطر تالٍ."""
    global _HYPHEN_RE
    if _HYPHEN_RE is None:
        _HYPHEN_RE = __import__('re').compile(r'([a-z])-\n([a-z])')
    prev = None
    while prev != text:
        prev = text
        text = _HYPHEN_RE.sub(r'\1\2', text)
    return text
