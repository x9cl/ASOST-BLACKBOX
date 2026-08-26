"""توليد PDF عربي احترافي مباشر — arabic_pdf.py
يستخدم WeasyPrint (HTML→PDF) مع دعم RTL كامل وخطوط عربية.
المدخل: نفس بنية صفحات compose_docx (text_with_markers + images)."""
import os, re, base64, html

IMG_MARK = re.compile(r'\[IMG:([^|\]]+)(?:\|([^\]]+))?\]')

HTML_TMPL = """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="utf-8">
<style>
  @page {{ size: A5; margin: 18mm 16mm;
           @bottom-center {{ content: counter(page); font-family: 'Noto Naskh Arabic'; font-size: 9pt; }} }}
  @page cover {{ margin: 0; @bottom-center {{ content: none; }} }}
  .coverpage {{ page: cover; }}
  body {{ font-family: 'Noto Naskh Arabic', 'Amiri', serif; font-size: 12pt;
         line-height: 1.9; text-align: justify; color: #1a1a1a; }}
  h1.title {{ text-align: center; font-size: 26pt; margin-top: 40%; page-break-after: always; }}
  h2.chapter {{ font-size: 16pt; text-align: center; margin: 24pt 0 18pt;
               page-break-before: always; color: #16213e; }}
  p {{ margin: 0 0 10pt; text-indent: 1.2em;
      text-align: justify; text-align-last: right;
      direction: rtl; }}
  img.illus {{ display: block; margin: 12pt auto; max-width: 85%; max-height: 70mm; }}
  img.fullpage {{ display: block; margin: 0 auto; width: 100%;
                 page-break-after: always; }}
  .illuspage {{ page: cover; }}
  .illuspage img {{ width: 100%; height: auto; }}
  img.cover {{ display: block; margin: 0 auto 20pt; max-width: 90%; }}
</style></head>
<body>
{cover}
<h1 class="title">{title}</h1>
{content}
</body></html>"""


def _img_src(path: str) -> str:
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{b64}"


def _render_block(block: str, images_map: dict) -> str:
    block = block.strip()
    if not block:
        return ''
    m = IMG_MARK.fullmatch(block)
    if m:
        name = m.group(1).strip()
        path = images_map.get(name) or os.path.join('images', name)
        if os.path.exists(path):
            cls_name = 'fullpage' if (m.group(2) or '') == 'full_page' else 'illus'
            if cls_name == 'fullpage':
                return f'<div class="illuspage"><img class="fullpage" src="{_img_src(path)}"></div>'
            return f'<img class="{cls_name}" src="{_img_src(path)}">'
        return f'<!-- missing image: {html.escape(name)} -->'
    return f'<p>{html.escape(block)}</p>'


def build_pdf(pages_flow, output_path, book_title="كتاب مترجم",
              cover_image=None, chapter_start_every=0):
    """pages_flow: [{"text_with_markers":..., "images": {name: abs_path}}, ...]"""
    cover = ''
    if cover_image and os.path.exists(cover_image):
        cover = f'<div class="coverpage"><img style="width:100%;" src="{_img_src(cover_image)}"></div>'

    parts = []
    for pi, page in enumerate(pages_flow):
        if chapter_start_every and pi > 0 and pi % chapter_start_every == 0:
            parts.append(f'<h2 class="chapter">— {pi // chapter_start_every + 1} —</h2>')
        images = page.get("images", {})
        for block in page.get("text_with_markers", "").split("\n\n"):
            rendered = _render_block(block, images)
            if rendered:
                parts.append(rendered)

    doc_html = HTML_TMPL.format(cover=cover, title=html.escape(book_title),
                                content="\n".join(parts))
    from weasyprint import HTML
    HTML(string=doc_html).write_pdf(output_path)
    return os.path.getsize(output_path)


if __name__ == '__main__':
    base = '/opt/data/projects/assost'
    out_dir = f'{base}/tests/composed'
    # اختبار: غلاف + صفحة مترجمة + رسمة
    img = f'{out_dir}/images/p1_x35.png'
    pages = [
        {"text_with_markers": "بدا الأمر وكأنه ميزة من ميزات الواقع المعزز، تشبه ألعاب الهواتف الذكية.\n\n«أم المفترض أن تكون هذه لعبة؟» أنينتُ بمرارة، محاولاً خداع أطرافي الواهنة لتتحرك.",
         "images": {}},
        {"text_with_markers": f"فقرة قبل الرسمة.\n\n[IMG:{os.path.basename(img)}|full_page]\n\nفقرة بعد الرسمة.",
         "images": {os.path.basename(img): img}},
    ]
    size = build_pdf(pages, f'{out_dir}/test_arabic.pdf',
                     book_title="Death March — المجلد الأول",
                     cover_image=img)
    print('PDF OK:', size, 'bytes')
