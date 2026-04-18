class ElicitationError(Exception):
    """Base class for elicitation-stage errors."""


class UnscopableClaimError(ElicitationError):
    """Raised when a claim cannot be scoped — e.g., no food identified."""


class InsufficientElicitationError(ElicitationError):
    """Raised when required slots remain unfilled after elicitation."""
