"""Настройки Немо и журнал операций."""
from __future__ import annotations

import csv
import getpass
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Settings:
    # Где хранить таблицу соответствий (ключ к обезличенному тексту). Пусто — папка Немо в AppData.
    session_dir: str = ""
    # False — таблица живёт только в памяти и пропадает при закрытии программы.
    keep_session: bool = True
    # Сеанс старше стольких дней очищается при запуске. 0 — не очищать.
    session_ttl_days: int = 7
    # Какие косвенные данные скрывать дополнительно: "DATE", "MONEY".
    optional_kinds: list[str] = field(default_factory=list)
    # Вести журнал операций (без самих данных: время, пользователь, что и сколько скрыто).
    journal: bool = False

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        try:
            s = cls(**known)
        except TypeError:
            return cls()
        s.optional_kinds = [k for k in s.optional_kinds if k in ("DATE", "MONEY")]
        s.session_ttl_days = max(0, int(s.session_ttl_days))
        return s

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    def session_path(self, default_dir: Path) -> Path:
        d = Path(self.session_dir) if self.session_dir else default_dir
        return d / "session.nemo"


JOURNAL_HEADER = ["время", "пользователь", "действие", "всего", "по типам"]


def journal_write(path: Path, action: str, kinds: list[str]) -> None:
    """Одна строка в CSV-журнал. Сами значения (ФИО, ИНН…) сюда не попадают."""
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    counts = Counter(kinds)
    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(JOURNAL_HEADER)
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), user, action, sum(counts.values()),
                    ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))])
