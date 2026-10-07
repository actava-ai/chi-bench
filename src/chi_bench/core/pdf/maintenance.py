"""Stable PDF bytes for maintenance of downloaded task artifacts."""

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def stable_pdf_bytes(path: Path) -> bytes:
    """Remove renderer timestamps so unchanged task PDFs keep the same hash."""
    reader = PdfReader(path)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.metadata = {
        key: value
        for key, value in (reader.metadata or {}).items()
        if key not in {"/CreationDate", "/ModDate"}
    }
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
