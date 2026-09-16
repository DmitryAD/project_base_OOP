"""
Модуль аудита: журнал событий банка. Хранит события в памяти и умеет
дописывать их на диск, а также фильтровать по нужным критериям.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime


class AuditSeverity:
    """
    Уровни важности события аудита.

    Мы намеренно НЕ используем enum.Enum здесь, а держим простые строковые
    константы класса — по той же схеме, что AccountStatus в main.py и
    ClientStatus в client.py. Так весь проект остаётся в одном стиле,
    вместо того чтобы в одном файле был enum, а в другом — класс-константы.
    """
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """
    @dataclass — декоратор, который сам генерирует __init__, __repr__ и
    __eq__ по объявленным ниже полям. Мы используем его здесь, потому что
    AuditEvent — это просто контейнер данных без своей сложной логики
    (в отличие, например, от BankAccount) — для таких классов dataclass
    это стандартный подход в проде: меньше кода, меньше шанс опечататься
    в ручном __init__.
    """
    event_id: str
    timestamp: datetime
    severity: str
    category: str
    message: str
    client_id: str = None
    # field(default_factory=dict) — нельзя писать `details: dict = {}`
    # напрямую: тогда ВСЕ экземпляры AuditEvent делили бы один и тот же
    # словарь (классическая ловушка изменяемых значений по умолчанию в
    # Python — тот же принцип, из-за которого мы используем **kwargs, а не
    # словарь-заглушку, в open_account). default_factory=dict говорит:
    # "при создании каждого нового объекта вызови dict() заново".
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        # asdict() — превращает dataclass в обычный словарь рекурсивно.
        # Дальше правим только timestamp, т.к. datetime сам по себе
        # не сериализуется в JSON — нужно превратить его в строку.
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    def __str__(self) -> str:
        client_part = f" client={self.client_id}" if self.client_id else ""
        return (
            f"[{self.severity.upper()}] {self.timestamp:%Y-%m-%d %H:%M:%S} "
            f"{self.category}:{client_part} {self.message}"
        )


class AuditLog:
    """Хранит события в памяти и, опционально, дублирует их в файл."""

    def __init__(self, file_path: str = None, time_provider=datetime.now):
        self.file_path = file_path
        self._time_provider = time_provider
        self._events: list[AuditEvent] = []
        self._counter = 0

    def record(self, severity: str, category: str, message: str, client_id: str = None, **details) -> AuditEvent:
        # **details — сюда прилетит всё, что вызывающий код передаст
        # именованными аргументами сверх обязательных (например,
        # amount=1000, risk_level="high"). Тот же приём, что и в
        # open_account с типоспецифичными параметрами счёта.
        self._counter += 1
        event = AuditEvent(
            event_id=f"AUD-{self._counter:06d}",
            timestamp=self._time_provider(),
            severity=severity,
            category=category,
            message=message,
            client_id=client_id,
            details=details,
        )
        self._events.append(event)
        if self.file_path:
            self._append_to_file(event)
        return event

    def _append_to_file(self, event: AuditEvent):
        # Режим "a" (append) — дописываем в конец файла, не стирая то,
        # что было записано раньше. Каждое событие — отдельная строка
        # валидного JSON (формат JSON Lines / NDJSON): удобно для логов,
        # т.к. файл можно читать построчно, не загружая целиком в память.
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def filter(self, severity: str = None, client_id: str = None, category: str = None, since: datetime = None) -> list:
        result = []
        for event in self._events:
            if severity is not None and event.severity != severity:
                continue
            if client_id is not None and event.client_id != client_id:
                continue
            if category is not None and event.category != category:
                continue
            if since is not None and event.timestamp < since:
                continue
            result.append(event)
        return result

    def __len__(self):
        return len(self._events)
