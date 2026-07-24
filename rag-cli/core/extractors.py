from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from common import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ExtractedPage:
    page_number: int
    text: str


@dataclass
class ExtractedDocument:
    title: str
    pages: list[ExtractedPage]
    full_text: str
    content_hash: str
    source_path: str


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_pdf(path: Path) -> ExtractedDocument:
    from pypdf import PdfReader

    logger.info("extracting_pdf", path=str(path))
    reader = PdfReader(str(path))
    pages: list[ExtractedPage] = []
    full_parts: list[str] = []

    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(ExtractedPage(page_number=i + 1, text=text))
        full_parts.append(text)

    full_text = "\n\n".join(full_parts)
    meta = reader.metadata
    title = ""
    if meta and meta.title:
        title = meta.title.strip()
    if not title:
        title = path.stem

    doc = ExtractedDocument(
        title=title,
        pages=pages,
        full_text=full_text,
        content_hash=_content_hash(full_text),
        source_path=str(path),
    )
    logger.info(
        "pdf_extracted",
        pages=len(pages),
        chars=len(full_text),
        hash=doc.content_hash[:12],
    )
    return doc


@dataclass
class ExtractedSection:
    heading: str
    level: int
    line_start: int
    line_end: int
    text: str


def extract_markdown(path: Path) -> ExtractedDocument:
    logger.info("extracting_markdown", path=str(path))
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    full_text = content

    title = path.stem
    first_heading = re.match(r"^#\s+(.+)$", content, re.MULTILINE)
    if first_heading:
        title = first_heading.group(1).strip()

    doc = ExtractedDocument(
        title=title,
        pages=[
            ExtractedPage(page_number=1, text=content),
        ],
        full_text=full_text,
        content_hash=_content_hash(full_text),
        source_path=str(path),
    )
    logger.info(
        "markdown_extracted",
        lines=len(lines),
        chars=len(full_text),
        hash=doc.content_hash[:12],
    )
    return doc


def extract_local_file(path: Path) -> ExtractedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    elif suffix in (".md", ".markdown"):
        return extract_markdown(path)
    else:
        raise ValueError(
            f"Unsupported file type {suffix!r}. Supported: .pdf, .md, .markdown"
        )
