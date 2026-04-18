"""Custom exceptions for Station 3: Retrieval."""

from typing import Optional


class RetrievalError(Exception):
    """Base class for all Station 3 errors."""


class InsufficientResultsError(RetrievalError):
    """Raised when PubMed returns fewer papers than the minimum threshold
    even after exhausting all relaxation levels."""


class PubMedAPIError(RetrievalError):
    """Base class for PubMed API errors. Kept for backward compatibility;
    prefer the more specific subclasses below."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class PubMedNetworkError(PubMedAPIError):
    """HTTP-level failure talking to NCBI: 4xx, 5xx, or transport error.

    ``status_code`` is set for HTTP responses and ``None`` for pure
    transport errors (ConnectionError, Timeout). Used by the retry
    predicate to decide whether to back off or fail fast.
    """


class PubMedParseError(PubMedAPIError):
    """Raised when a PubMed response body could not be parsed (malformed
    JSON or XML). These are not retried — bad data won't get better."""


class PubMedRateLimitError(PubMedNetworkError):
    """Specifically a 429 Too Many Requests. Kept for existing callers."""

    def __init__(self, message: str):
        super().__init__(message, status_code=429)


class UnretrievableClaimError(RetrievalError):
    """Raised when the LockedPICO is missing both 'food' and 'outcome',
    making it impossible to build any meaningful PubMed query."""


class CAERSAPIError(RetrievalError):
    """HTTP-level failure talking to openFDA CAERS. 404s are handled
    gracefully in the client (treated as "no results") and never reach
    this exception; anything else is a real failure."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
