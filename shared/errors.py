class GeometryCognitionError(Exception):
    """Base error for project-level exceptions."""


class ContractValidationError(GeometryCognitionError):
    """Raised when payload validation fails."""
