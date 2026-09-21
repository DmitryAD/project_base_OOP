"""Клиент банка."""

import hashlib
import hmac
import secrets
import uuid
from datetime import date

from exceptions import InvalidOperationError, UnderageClientError


class ClientStatus:
    """Допустимые статусы клиента."""

    ACTIVE = "active"
    BLOCKED = "blocked"


class Client:
    """Клиент банка: личные данные, контакты, статус и список счетов.

    Пароль не хранится: сохраняются только соль и хеш PBKDF2-HMAC-SHA256.
    PBKDF2 намеренно медленный, что делает перебор паролей дорогим.
    Число итераций запоминается для каждого клиента, поэтому его можно
    увеличить в будущем без поломки уже сохранённых хешей.
    """

    MIN_AGE = 18
    PBKDF2_ITERATIONS = 600_000

    def __init__(
        self,
        full_name: str,
        birth_date: date,
        *,
        password: str,
        phone: str | None = None,
        email: str | None = None,
        client_id: str | None = None,
    ):
        if not isinstance(full_name, str) or not full_name.strip():
            raise InvalidOperationError("Некорректное ФИО клиента.")
        if not isinstance(birth_date, date):
            raise InvalidOperationError("Дата рождения должна быть объектом date.")

        self.full_name = full_name
        self.birth_date = birth_date
        if self.age < self.MIN_AGE:
            raise UnderageClientError(
                f"Клиент должен быть не младше {self.MIN_AGE} лет (сейчас: {self.age})."
            )

        self.client_id = client_id or uuid.uuid4().hex[:8]
        self.phone = phone
        self.email = email
        self.status = ClientStatus.ACTIVE
        self.account_ids: list[str] = []

        self._salt = b""
        self._password_hash = b""
        self._iterations = self.PBKDF2_ITERATIONS
        self.set_password(password)

    @property
    def age(self) -> int:
        today = date.today()
        had_birthday = (today.month, today.day) >= (self.birth_date.month, self.birth_date.day)
        return today.year - self.birth_date.year - (0 if had_birthday else 1)

    def set_password(self, password: str):
        if not isinstance(password, str) or not password:
            raise InvalidOperationError("Пароль должен быть непустой строкой.")
        self._salt = secrets.token_bytes(16)
        self._iterations = self.PBKDF2_ITERATIONS
        self._password_hash = self._hash_password(password, self._salt, self._iterations)

    def verify_password(self, password: str) -> bool:
        """Проверяет пароль сравнением за постоянное время (защита от timing-атак)."""
        if not isinstance(password, str):
            return False
        candidate = self._hash_password(password, self._salt, self._iterations)
        return hmac.compare_digest(candidate, self._password_hash)

    @staticmethod
    def _hash_password(password: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

    def __str__(self) -> str:
        return (
            f"Client | {self.full_name} | ID: {self.client_id} | "
            f"Возраст: {self.age} | Статус: {self.status} | Счетов: {len(self.account_ids)}"
        )
