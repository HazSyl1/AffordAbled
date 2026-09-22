from passlib.context import CryptContext


class Argon2PasswordHasher:
    """Argon2 avoids a known passlib/bcrypt incompatibility (bcrypt>=4.1
    rejects passlib's legacy self-test with long inputs) and is the
    stronger current default for new password hashing."""

    def __init__(self) -> None:
        self._context = CryptContext(schemes=["argon2"], deprecated="auto")

    def hash(self, plain_password: str) -> str:
        return self._context.hash(plain_password)

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        return self._context.verify(plain_password, hashed_password)

