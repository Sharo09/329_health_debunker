"""Custom exceptions for Station 3: Retrieval."""


class RetrievalError(Exception):
    """Base class for all Station 3 errors."""


class InsufficientResultsError(RetrievalError):
    """Raised when PubMed returns fewer papers than the minimum threshold
    even after exhausting all relaxation levels."""


class PubMedAPIError(RetrievalError):
    """Raised when the PubMed E-utilities API returns an unexpected error
    that cannot be resolved by retry."""


class UnretrievableClaimError(RetrievalError):
    """Raised when the LockedPICO is missing both 'food' and 'outcome',
    making it impossible to build any meaningful PubMed query."""