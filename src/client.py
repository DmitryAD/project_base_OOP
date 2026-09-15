import uuid
from datetime import date

from exceptions import InvalidOperationError, UnderageClientError


class ClientStatus:
    ACTIVE = "active"
    BLOCKED = "blocked"


class Client:
    """Клиент банка: ФИО, дата рождения, контакты, список ID своих счетов, статус."""

    MIN_AGE = 18  # атрибут класса — единая точка правды про минимальный возраст

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
        self.password = password  # упрощённо: в реальном проекте пароль всегда хранят хешем, не открытым текстом
        self.status = ClientStatus.ACTIVE
        self.account_ids = []  # список ID счетов клиента (не сами объекты счетов — только ссылки на них)

        # проверка возраста делается в самом конце __init__, когда все
        # остальные поля уже выставлены — self.age (см. ниже) их не использует,
        # но такой порядок логичнее: сначала собрать объект, потом провалидировать целиком
        if self.age < self.MIN_AGE:
            raise UnderageClientError(
                f"Клиент должен быть не младше {self.MIN_AGE} лет (сейчас: {self.age})."
            )

    @staticmethod
    def _generate_client_id() -> str:
        return str(uuid.uuid4().int)[:8]

    @property
    def age(self) -> int:
        # === НОВОЕ: @property ===
        # @property превращает метод в "вычисляемый атрибут": снаружи его
        # читают БЕЗ круглых скобок — client.age, а не client.age().
        # Смысл: возраст не хранится как отдельное поле (self._age = ...),
        # потому что он бы устаревал каждый день рождения. Вместо этого он
        # каждый раз СЧИТАЕТСЯ заново из birth_date — это гарантирует, что
        # client.age всегда актуален на момент обращения.
        today = date.today()
        years = today.year - self.birth_date.year
        # если день рождения в этом году ещё не наступил (сравниваем
        # кортежи (месяц, день) — Python сравнивает их поэлементно,
        # как строки) — вычитаем один год, чтобы не засчитать "будущий" ДР
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
