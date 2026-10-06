"""Task artifact hashes must not depend on PDF rendering timestamps."""

from io import BytesIO

from pypdf import PdfReader, PdfWriter

from chi_bench.core.pdf.maintenance import stable_pdf_bytes


def test_pdf_timestamps_do_not_change_artifact_bytes(tmp_path):
    rendered = []
    for index, timestamp in enumerate(("D:20261006120000Z", "D:20261006120100Z")):
        path = tmp_path / f"form-{index}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=144)
        writer.add_metadata(
            {
                "/Title": "Prior authorization request",
                "/CreationDate": timestamp,
                "/ModDate": timestamp,
            }
        )
        writer.write(path)
        rendered.append(stable_pdf_bytes(path))

    assert rendered[0] == rendered[1]
    reader = PdfReader(BytesIO(rendered[0]))
    assert reader.metadata.title == "Prior authorization request"
    assert "/CreationDate" not in reader.metadata
    assert "/ModDate" not in reader.metadata
    assert len(reader.pages) == 1
    assert reader.pages[0].mediabox.width == 72
    assert reader.pages[0].mediabox.height == 144
