from io import BytesIO
from zlib import error as ZlibError

from pypdf import PdfReader
from pypdf.errors import DependencyError, PdfReadError

from app.schemas import PageText


class InvalidPDFError(ValueError):
    """The file cannot be used as a text-based PDF."""


class PDFPageLimitError(ValueError):
    """The document exceeds the configured page limit."""


def extract_pdf_pages(content: bytes, max_pages: int) -> list[PageText]:
    """Extract text while preserving all page numbers, including blank pages."""
    if not content.startswith(b"%PDF-"):
        raise InvalidPDFError("The file does not contain a valid PDF header.")

    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise InvalidPDFError("Encrypted PDFs are not supported.")

        if len(reader.pages) > max_pages:
            raise PDFPageLimitError(f"PDFs must contain at most {max_pages} pages.")

        pages = [
            PageText(page_number=number, text=(page.extract_text() or "").strip())
            for number, page in enumerate(reader.pages, start=1)
        ]
    except (InvalidPDFError, PDFPageLimitError):
        raise
    except (
        PdfReadError, DependencyError, ValueError, TypeError, KeyError,
        IndexError, NotImplementedError, ZlibError,
    ) as error:
        raise InvalidPDFError("The PDF is damaged or could not be read.") from error

    if not any(page.text for page in pages):
        raise InvalidPDFError(
            "The PDF contains no extractable text. Scanned PDFs require OCR, "
            "which is not supported."
        )

    return pages
