

---

## 🎯 دورة #3-4: هدف الجودة تحقق (تشغيل مباشر بأمر أنس)

### المشكلة المكتشفة
المقياس الآلي كان يعاقب ترجمة صحيحة: «303» تُرجمت أدبياً «ثلاثمائة وثلاثة» — والمقياس يبحث عن الأرقام فقط.

### الإصلاحات (compare.py + المحرك)
1. few-shot examples معتمدة محقونة في المعجم
2. مقياس الأرقام يقبل: الكلمات العربية، الأرقام الشرقية ٠-٩، فك أدوات الربط (وثلاثة=ثلاثة)، جمع القيم المتتالية (300+3=303)

### النتيجة النهائية (v3)
**الجودة: 98.0/100** | الاتساق: 3/3 ✓ | **الهدف ≥95 محقق**

---
## TARGET REACHED - cycles 3-4 (direct run per Anas)
- Issue: metric penalized correct literary translation (303 = ثلاثمائة وثلاثة)
- Fixes: few-shot injection + number metric accepts Arabic words/Eastern digits/conjunction stripping/composite sums
- RESULT v3: 98.0/100 | consistency 3/3 | target >=95 ACHIEVED


---
## GOAL 2 cycles (extraction + PDF composition)
### Cycle 1 results:
- Text retention: 100.7% (extracted > raw due to hyphen-merge)
- Hyphenation fix: 47 broken words -> 0 (new _fix_hyphenation helper)
- Illustrations: 7 detected, mapped to chapters
### Cycle 2 (PDF composition):
- Vision audit found: paragraphs not justified (centered look)
- Fix: CSS text-align justify + text-align-last right + direction rtl
- Dense-page verification: both edges aligned, RTL correct, page numbers present
- Final PDF: 34 pages, cover + ch2 illustration embedded

### Cycle 4 (cover + title page polish):
- Cover page: full-bleed image, NO page number (named @page cover)
- Title page: Death March - Arabic title renders correctly (bidi mixed-direction OK)
- Verified via vision audit on rendered pages

---
## GOAL 2 COMPLETE - final audit (cycle 6)
EXTRACTION: 187 blocks, hyphenation 64 raw -> 0 after fix, 7 illustrations detected
COMPOSITION: all 7 checks PASS (cover/title/toc/headings/no-seams/no-margin-violations)
Deliverables: tests/fullbook/full_book.pdf (34p) + full_book.docx + full_book_ar.txt.clean
STATUS: Goal 1 (translation) + Goal 2 (extraction+composition) BOTH COMPLETE

---
## GOAL 2 FINAL CERTIFICATION (cycle 7)
- Regression found & fixed: cover duplicated (in openers list) -> excluded
- Final audit: all_present=true | no_duplicates=true | full-bleed sizing verified
- Context binding verified: ill24 between its two narrative passages
- Deliverable rebuilt: 39 pages
STATUS: GOAL 2 COMPLETE

---
## GOAL 2 REBUILD — المؤلّف الحتمي (deterministic_composer/render) — دورة جديدة بأمر أنس
### التشخيص الجذري
- الطريقة القديمة (ContextImagePlacer) كانت تخميناً نصياً بالأرقام → "NO MATCH, skipped" = عمى.
- الاكتشاف المفتاحي: الترجمة محفوظة صفحة-بصفحة (paged_translations.json) بمفتاح رقم الصفحة الأصلية
  → موضع الصورة معروف هندسياً (y-order) بلا أي تخمين.
### الحل الجديد (بلا استدلال)
- deterministic_composer.py: كل صفحة أصلية = وحدة مخرج بنفس ترتيب عناصرها.
  رسمة كاملة = صفحة صورة كاملة؛ نص = ترجمة نفس الصفحة؛ الأحجام من bbox نسبةً لعرض الصفحة.
- deterministic_render.py: PDF (WeasyPrint) + DOCX من نفس pages_flow.
  مقاس الصفحة = مقاس الأصل 410×600pt؛ كل وحدة تبدأ صفحة جديدة (شرط التطابق 1:1).
- deterministic_verify.py: مصفوفة تحقق حتمية (تسلسل العناصر، تسرب العلامات، الأحجام).
### نتائج التحقق النهائية
- محاذاة الصفحات: 23/23 (كل وحدة نصية في صفحتها الأصلية بالضبط)
- نمط التسلسل: الأصل FFFFFF T×23 F T×9 == المخرج (بعد الغلاف C) — تطابق تام
- لا علامات [IMG] مسربة، لا صور مفقودة، الرسمة ص24 في موضعها بحجم كامل
- تدقيق بصري: RTL سليم، ضبط أسطر، رسمة كاملة بلا رقم صفحة
- المخرجات: tests/fullbook/deterministic/det_book.pdf (31p) + det_book.docx

---
## دورة #2 — تعميم الحل + إصلاحات التحقق
- اختبار E2E لصفحة مختلطة (نص+صورة داخلية): العلامة تُدرج في الموضع الهندسي الصحيح بين الفقرات ✓
- إصلاح: skip_cover كان يحذف أي صفحة 1 نصية → الآن الغلاف = رسمة كاملة فقط
- إصلاح: الصور الداخلية (frac<0.98) لم تعد تكسر الصفحة (illus-inline بدل illuspage)
- إصلاح أداة التحقق: cover يُكافئ full في V1/V2؛ ALL_PASS أصبح منطقياً سليماً
- النتيجة النهائية على الكتاب الرئيسي: ALL_PASS=True
  (7/7 صفحات رسمات، تسلسل مطابق، صفر تسريب، 23/23 محاذاة نص)
- المخرجات: tests/fullbook/deterministic/det_book.pdf (31p) + det_book.docx

---
## دورة #3 — الربط بالداشبورد (server.py) ✓
- بعد اكتمال كل مهمة ترجمة: المؤلّف الحتمي يُشغَّل تلقائياً
  (يقرأ paged_translations.json من مجلد الإخراج → يبني PDF مطابق للأصل)
- عمود deterministic_pdf_path في قاعدة المهام + ترحيل تلقائي للقواعد القديمة
- تحقق: syntax OK، استيراد سليم، السيرفر أقلع فعلياً (/api/health = ok, 9 keys)
- الحالة: المؤلّف الحدمي هو الآن مسار إخراج موازٍ لكل كتاب جديد

---
## دورة التدقيق العميق والإصلاحات (2026-08-26) — إدارة Orchestrator عبر subagents

### سلسلة التنفيذ الكاملة (9 مهام مفوضة):
1. Builder → بوابات session_context (register_session_source)
2. Builder → credential pool (hermes-home/auth.json)
3. Builder → toolsets ASOST الثلاثة + asost_tools.py
4. Builder → الوكلاء الدائمون الستة + orchestrator
5. Builder → ربط الداشبورد (/api/asost/*)
6. Tester → E2E أول (كشف: درجات منخفضة + JSON مكسور)
7. Builder → reviser + JSON صارم → 3/3 accepted 88/100
8. **Auditor → تدقيق عميق قراءة-فقط**: 1010 ملف، 46 نصاً — 3 HIGH/4 MED/5 LOW
9. Builder → الإصلاحات الستة R1-R6 + 6 اختبارات قبول

### نتائج التدقيق:
- بنية Hermes: مطابقة بايت-بايت للنواة، صفر نواقص
- الرواية: 100% سلامة (لا فراغ/اقتطاع، خياطة مستمرة p15→16, p29→30)
- أمان: لا تسريب مفاتيح

### الإصلاحات المنفذة:
R1 _extract_score تكراري (nested→85 ✓)
R2 auth توكن + حد 20k حرف + cap 50 jobs
R3 برومبت JSON موحد للنقدين
R4 timeout 300s + رفض نص <50 حرف
R5 retry فصل قاتل/مؤقت + jitter ±20% + log key index
R6 حذف critique placeholder + تصحيح العدد

### الحالة النهائية: ALL_PASS | 3/3 E2E accepted 88/100 | كل الثغرات مغلقة
