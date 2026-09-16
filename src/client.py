import hashlib
import hmac
import secrets
import uuid
from datetime import date

from exceptions import InvalidOperationError, UnderageClientError


class ClientStatus:
    ACTIVE = "active"
    BLOCKED = "blocked"


class Client:
    """Клиент банка: ФИО, дата рождения, контакты, список ID своих счетов, статус."""

    MIN_AGE = 18

    def __init__(
        self,
        full_name: str,
        birth_date: date,
        phone: str = None,
        email: str = None,
        password: str = "1234",
        client_id: str = None,
    ):
        if not full_name or not isinstance(full_name, str):
            raise InvalidOperationError("Некорректное ФИО клиента.")

        self.client_id = client_id or self._generate_client_id()
        self.full_name = full_name
        self.birth_date = birth_date
        self.phone = phone
        self.email = email
        self.status = ClientStatus.ACTIVE
        self.account_ids = []

        """
        НОВОЕ: пароль больше не хранится напрямую. Вместо self.password
        вызываем set_password(password), который сам создаёт соль и хеш
        и сохраняет их в self._salt и self._password_hash. Само значение
        password нигде не остаётся в объекте после этой строки.
        """
        self._salt = None
        self._password_hash = None
        self.set_password(password)

        if self.age < self.MIN_AGE:
            raise UnderageClientError(
                f"Клиент должен быть не младше {self.MIN_AGE} лет (сейчас: {self.age})."
            )

    @staticmethod
    def _generate_client_id() -> str:
        return str(uuid.uuid4().int)[:8]

    def set_password(self, password: str):
        """
        Задать (или сменить) пароль клиента.

        secrets.token_hex(16) — генерирует криптографически надёжную
        случайную строку из 16 байт, представленную как 32 hex-символа.
        Модуль secrets (в отличие от random) предназначен именно для
        значений, связанных с безопасностью — паролей, токенов, ключей —
        потому что его генератор случайности криптографически стойкий,
        а обычный random таким не является и предсказуем при определённых
        условиях.

        hashlib.sha256(...).hexdigest() — считает хеш SHA-256 от байтовой
        строки и возвращает его как обычную читаемую hex-строку.
        Перед хешированием склеиваем соль и пароль (salt + password) —
        это и есть "подмешивание" соли.
        """
        self._salt = secrets.token_hex(16)
        self._password_hash = self._hash_password(password, self._salt)

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        raw = (salt + password).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def verify_password(self, password: str) -> bool:
        """
        Проверить, совпадает ли введённый пароль с сохранённым хешем.

        Считаем хеш от (сохранённая соль + введённый пароль) и сравниваем
        с self._password_hash. Используем hmac.compare_digest вместо
        обычного == — это сравнение, устойчивое к timing-атакам: обычное
        == останавливается на первом несовпадающем символе, и по времени
        выполнения теоретически можно угадывать пароль посимвольно.
        compare_digest всегда сравнивает за одинаковое время, независимо
        от того, где нашлось несовпадение.
        """
        candidate_hash = self._hash_password(password, self._salt)
        return hmac.compare_digest(candidate_hash, self._password_hash)

    @property
    def age(self) -> int:
        today = date.today()
        years = today.year - self.birth_date.year
        had_birthday_this_year = (today.month, today.day) >= (
            self.birth_date.month,
            self.birth_date.day,
        )
        if not had_birthday_this_year:
            years -= 1
        return years

    def __str__(self):
        return (
            f"Client | {self.full_name} | ID: {self.client_id} | "
            f"Возраст: {self.age} | Статус: {self.status} | Счетов: {len(self.account_ids)}"
        )
