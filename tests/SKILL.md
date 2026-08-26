# ASOST Translation Engine — Dev & Test Workflow

Use when developing/testing Anas's ASOST book-translation engine at /opt/data/projects/assost/assost-main.

## Environment
- Venv: `assost-main/.venv` (created via uv). Run: `assost-main/.venv/bin/python`
- Baseline book: `/opt/data/projects/assost/book.pdf` (Death March Vol.01, 30 pages)
- Keys: 9 Gemini keys in `assost-main/.env` as `ASOST_GEMINI_KEYS=...` (comma-separated). Model: gemini-3.5-flash (2.5-flash/pro blocked for new users; 3.7-flash hangs on free tier).
- Keys are loaded by `PF.EnhancedGeminiAPI._load_keys_from_env()` — never hardcode keys.

## Test assets
- Samples: `tests/samples/` (text_p20/p27/p30 hard-text; mixed_p7/p20 text+images) + manifest.json
- Baseline outputs: `tests/baseline/` + quality_report.json (avg 91.3/100)
- Comparator: `tests/compare.py <dir>` — metrics: arabic_ratio, leftover English, number preservation (note: engine converts numbers to Arabic words, so digit-metric reads low — not a real defect), length ratio, dialogue/paragraph alignment.

## Image-aware pipeline (new modules)
- `assost-main/image_aware_extract.py` → `extract_page_flow(pdf, page_idx, images_dir)` returns flow items [{type:text|image,...}] sorted by y, plus `text_with_markers` embedding `[IMG:file|class]`. Classifies images by SIZE only (full_page ≥300px, illustration ≥100px, decorations filtered). No vision analysis in the pipeline.
- `assost-main/compose_docx.py` → standalone Arabic RTL DOCX builder with cover.
- `PF.EnhancedDocumentGenerator.create_novel_document` now supports `[IMG:name]` paragraphs; chapter dict may carry `images_map: {name: abs_path}`.
- Book structure: pages 1-6+24 = full-page illustrations; page 20 has only small SFX decorations (~11pt tall) — correctly filtered; page 22 tiny ornament.

## Pitfalls
- `fitz` import warns deprecation → use pymupdf name eventually; harmless.
- create_novel_document requires toc entries to have BOTH arab_title? No — needs `original_title` key present or KeyError; include `{"arabic_title","original_title"}`.
- curl test API: use header `x-goog-api-key: KEY`, NOT `?key=` (AQ.Ab8 keys fail as query param).
- Don't translate full books — samples only (Anas's policy); each sample ≈1500 chars.
