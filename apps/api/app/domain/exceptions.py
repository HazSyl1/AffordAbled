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


class InvalidSpeechInputError(DomainError):
    'Raised when uploaded voice input is missing or unsupported.'


class InvalidChatInputError(DomainError):
    'Raised when chat input is missing or invalid.'


class SpeechServiceNotConfiguredError(DomainError):
    'Raised when speech service credentials/region are missing.'


class SpeechTranscriptionError(DomainError):
    'Raised when speech-to-text provider fails to produce a transcript.'
