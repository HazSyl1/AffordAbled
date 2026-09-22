class DomainError(Exception):
    'Base class for all domain-level errors.'


class UserAlreadyExistsError(DomainError):
    'Raised when registering an email that is already in use.'


class InvalidCredentialsError(DomainError):
    'Raised on email/password login failure.'


class InvalidTokenError(DomainError):
    'Raised when an access/refresh token is missing, malformed, expired, or revoked.'


class AccountNotFoundError(DomainError):
    'Raised both when an account does not exist and when it belongs to a different user.'


class CategoryNotFoundError(DomainError):
    'Raised both when a category does not exist and when it belongs to a different user.'


class TransactionNotFoundError(DomainError):
    'Raised both when a transaction does not exist and when it belongs to a different user.'


class InvalidTransactionError(DomainError):
    'Raised when transaction fields violate deterministic business rules.'
