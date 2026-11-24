"""Сеанс обезличивания: метки, таблица соответствий, обратная подстановка."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .detectors import (LABELS, Entity, NatashaNER, find_custom, find_regex,
                        resolve_overlaps)

AI_HINT = (
    "Важно: в тексте ниже персональные данные заменены метками в квадратных скобках, "
    "например [ЧЕЛОВЕК_1] или [ИНН_2]. Используй эти метки в ответе ровно в таком виде, "
    "не склоняй и не изменяй их.\n\n"
)

# Метка в ответе нейросети: допускаем потерянные скобки, пробел/дефис вместо «_», Е вместо Ё.
_LABEL_ALT = "|".join(sorted({re.escape(v) for v in LABELS.values()} | {"СЧЕТ"}, key=len, reverse=True))
# Без скобок принимаем только вариант с подчёркиванием, чтобы не задеть обычное «место 1».
RE_TOKEN = re.compile(
    r"\[\s*(" + _LABEL_ALT + r")[ _\-]?(\d+)\s*\]"
    r"|(?<![\w])(" + _LABEL_ALT + r")_(\d+)(?![\w])",
    re.I,
)


@dataclass
class Item:
    token: str        # [ЧЕЛОВЕК_1]
    kind: str         # PER
    value: str        # что подставим обратно
    variants: list[str] = field(default_factory=list)  # как встречалось в тексте


class Session:
    """Хранит соответствия «метка ↔ значение». Одинаковое значение → одна метка."""

    def __init__(self):
        self.items: dict[str, Item] = {}       # token -> Item
        self.by_key: dict[str, str] = {}       # entity.key -> token
        self.counters: dict[str, int] = {}
        self.manual: list[str] = []            # фразы, которые пользователь скрыл вручную

    # ------------------------------------------------------------ скрытие
    def _token_for(self, e: Entity) -> str:
        key = e.key
        if key in self.by_key:
            tok = self.by_key[key]
            it = self.items[tok]
            if e.text not in it.variants:
                it.variants.append(e.text)
            return tok
        label = LABELS[e.kind]
        n = self.counters.get(label, 0) + 1
        self.counters[label] = n
        tok = f"[{label}_{n}]"
        # Для ФИО и мест возвращаем нормальную форму («Иванов Иван»), для остального — как было.
        value = e.normal if (e.kind in ("PER", "LOC") and e.normal) else e.text
        self.items[tok] = Item(tok, e.kind, value, [e.text])
        self.by_key[key] = tok
        return tok

    def anonymize(self, text: str, ner: NatashaNER | None = None,
                  custom_words: list[str] | None = None,
                  manual: list[str] | None = None) -> tuple[str, list[Entity]]:
        ents = find_regex(text)
        if ner is not None:
            ents += ner.find(text)
        ents += find_custom(text, (custom_words or []) + self.manual + (manual or []))
        ents = resolve_overlaps(ents)

        parts, pos = [], 0
        for e in ents:
            parts.append(text[pos:e.start])
            parts.append(self._token_for(e))
            pos = e.end
        parts.append(text[pos:])
        return "".join(parts), ents

    # ------------------------------------------------------------ возврат
    def _lookup(self, label: str, num: str) -> Item | None:
        label = label.upper()
        if label == "СЧЕТ":
            label = "СЧЁТ"
        return self.items.get(f"[{label}_{int(num)}]")

    def restore(self, text: str) -> tuple[str, int, list[str]]:
        """Возвращает (текст, сколько подставлено, метки без соответствия)."""
        missing: list[str] = []
        count = 0

        def repl(m: re.Match) -> str:
            nonlocal count
            label = m.group(1) or m.group(3)
            num = m.group(2) or m.group(4)
            it = self._lookup(label, num)
            if it is None:
                missing.append(m.group(0))
                return m.group(0)
            count += 1
            return it.value

        return RE_TOKEN.sub(repl, text), count, missing

    # ------------------------------------------------------------ хранение
    def to_dict(self) -> dict:
        return {
            "items": [vars(i) for i in self.items.values()],
            "by_key": self.by_key,
            "counters": self.counters,
            "manual": self.manual,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        s = cls()
        for raw in d.get("items", []):
            it = Item(**raw)
            s.items[it.token] = it
        s.by_key = dict(d.get("by_key", {}))
        s.counters = dict(d.get("counters", {}))
        s.manual = list(d.get("manual", []))
        return s

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Session":
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return cls()
