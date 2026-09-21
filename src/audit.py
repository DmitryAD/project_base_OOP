"""Журнал аудита: хранение событий в памяти и в файле, фильтрация."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime


class AuditSeverity:
    """Уровни важности событий аудита."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Одно событие аудита."""

    event_id: str
    timestamp: datetime
    severity: str
    category: str
    message: str
    client_id: str | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
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
    """Журнал событий в памяти с необязательной записью в файл.

    Файл пишется в формате JSON Lines: одна строка — одно событие.
    Такой файл можно дописывать и читать построчно, не загружая целиком.
    """

    def __init__(self, file_path: str | None = None, time_provider=datetime.now):
        self.file_path = file_path
        self._time_provider = time_provider
        self._events: list[AuditEvent] = []

    def record(
        self,
        severity: str,
        category: str,
        message: str,
        client_id: str | None = None,
        **details,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=f"AUD-{len(self._events) + 1:06d}",
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
        """Дописывает событие в файл; default=str сериализует Decimal и другие типы."""
        with open(self.file_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")

    def filter(
        self,
        severity: str | None = None,
        client_id: str | None = None,
        category: str | None = None,
        since: datetime | None = None,
    ) -> list[AuditEvent]:
        """Возвращает события, удовлетворяющие всем заданным условиям, в порядке записи."""
        return [
            event
            for event in self._events
            if (severity is None or event.severity == severity)
            and (client_id is None or event.client_id == client_id)
            and (category is None or event.category == category)
            and (since is None or event.timestamp >= since)
        ]

    def __len__(self) -> int:
        return len(self._events)
