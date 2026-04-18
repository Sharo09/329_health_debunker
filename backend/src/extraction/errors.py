class ExtractionError(Exception):
    """Base class for Station 1 extraction errors."""


class EmptyClaimError(ExtractionError):
    """Raised when the input claim is empty or whitespace-only."""
