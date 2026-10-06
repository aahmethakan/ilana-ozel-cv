class PDFParserError(Exception):
    """Base error raised when PDF source evidence cannot be extracted."""


class EmptyPDFInputError(PDFParserError):
    """Raised when no PDF bytes or filename are supplied."""


class InvalidPDFError(PDFParserError):
    """Raised when the input is not a readable PDF."""


class EncryptedPDFError(PDFParserError):
    """Raised when a PDF requires a password and cannot be read."""


class NoMachineReadableTextError(PDFParserError):
    """Raised for image-only or otherwise textless PDFs."""


class PDFInputTooLargeError(PDFParserError):
    """Raised when PDF input exceeds the configured parser limit."""


class PDFPageLimitExceededError(PDFParserError):
    """Raised before extraction when a PDF has too many pages."""
