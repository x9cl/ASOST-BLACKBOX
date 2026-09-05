"""Deterministic adapters around the existing ASOST document engine."""

from __future__ import annotations

import sys
import importlib
from pathlib import Path
from typing import Any

from asost.config import settings


def _load_document_components():
    engine_path = str(settings.asost_main)
    if engine_path not in sys.path:
        sys.path.insert(0, engine_path)
    module = importlib.import_module("PF")
    return module.ProfessionalDocumentProcessor, module.EnhancedDocumentGenerator


def extract_pdf(pdf_path: str | Path) -> dict[str, Any]:
    """Extract pages, chapters, metadata, and image mappings without an LLM."""
    processor, _ = _load_document_components()
    return processor.extract_pdf_with_precision(str(pdf_path))


def compose_docx(chapters: list[dict[str, Any]], output_path: str | Path,
                 title: str, author: str,
                 table_of_contents: list[dict[str, Any]] | None = None) -> str:
    """Compose accepted chapters using the existing deterministic DOCX builder."""
    _, generator = _load_document_components()
    return generator.create_novel_document(
        chapters, str(output_path), title, author, table_of_contents or []
    )


def verify_docx(path: str | Path, expected_chapters: int,
                expected_toc: int = 0) -> dict[str, Any]:
    """Run the existing structural document verifier."""
    _, generator = _load_document_components()
    return generator.verify_document(str(path), expected_chapters, expected_toc)
