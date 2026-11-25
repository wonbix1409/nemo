"""Сеанс обезличивания: метки, таблица соответствий, обратная подстановка."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .declension import (decline_person, decline_place, detect_case, gender_of,
                         infer_case, normalize_case)
from .detectors import (LABELS, Entity, NatashaNER, find_custom, find_regex,
                        fullness, is_patronymic, normalize_fio, person_signature,
                        resolve_overlaps, same_person, trim_person)


def person_form(sig: dict) -> str:
    """Какая это форма упоминания: полное ФИО (""), имя-отчество («ИО») или фамилия с инициалами («ИНИЦ»)."""
    if sig.get("surn") and sig.get("name"):
        return ""
    if sig.get("name"):
        return "ИО"
    return "ИНИЦ" if sig.get("surn") else ""

AI_HINT = (
    "Важно: в тексте ниже персональные данные заменены метками в квадратных скобках, "
    "например [ЧЕЛОВЕК_1] или [ИНН_2]. Пиши метки в ответе так же, в квадратных скобках, "
    "не меняя слов и номеров внутри. Падеж указан после черты: [ЧЕЛОВЕК_1|рд] — родительный "
    "(кого?), |дт — дательный (кому?), |вн — винительный, |тв — творительный (кем?), "
    "|пр — предложный (о ком?); без черты — именительный. Когда в твоём ответе человек или место "
    "стоит в другом падеже, ставь нужную черту сам, например «полномочия [ЧЕЛОВЕК_1|рд]». "
    "Метки с одним номером — один и тот же человек: [ЧЕЛОВЕК_1.ИО] — он же по имени и отчеству, "
    "[ЧЕЛОВЕК_1.ИНИЦ] — он же с инициалами.\n\n"
)

# Метка в ответе нейросети: допускаем потерянные скобки, пробел/дефис вместо «_», Е вместо Ё.
_LABEL_ALT = "|".join(sorted({re.escape(v) for v in LABELS.values()} | {"СЧЕТ"}, key=len, reverse=True))
# Без скобок принимаем только вариант с подчёркиванием, чтобы не задеть обычное «место 1».
RE_TOKEN = re.compile(
    r"\[\s*(?P<l1>" + _LABEL_ALT + r")[ _\-]?(?P<n1>\d+)(?:\.(?P<f1>ИО|ИНИЦ))?"
    r"(?:\s*\|\s*(?P<c1>[А-Яа-яЁё.]{1,12}))?\s*\]"
    r"|(?<![\w])(?P<l2>" + _LABEL_ALT + r")_(?P<n2>\d+)(?:\.(?P<f2>ИО|ИНИЦ))?(?![\w])",
    re.I,
)


@dataclass
class Item:
    token: str        # [ЧЕЛОВЕК_1]
    kind: str         # PER
    value: str        # что подставим обратно
    variants: list[str] = field(default_factory=list)  # как встречалось в тексте
    sig: dict = field(default_factory=dict)             # подпись человека (фамилия + инициалы)
    forms: dict = field(default_factory=dict)           # «ИО» → «Аркадий Геннадьевич», «ИНИЦ» → «Белоусов А.Г.»


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
            it = self.items[re.sub(r"\.(ИО|ИНИЦ)\]$", "]", tok)]
            if e.text not in it.variants:
                it.variants.append(e.text)
            return tok
        # Тот же человек в другом виде: «Белоусов А.Г.», «Аркадий Геннадьевич», другой падеж.
        # Номер метки общий, а форма — своя: [ЧЕЛОВЕК_1.ИО] вернётся как «Аркадий Геннадьевич».
        if e.kind == "PER":
            val = e.normal or e.text
            sig = person_signature(val)
            for it in self.items.values():
                if it.kind == "PER" and same_person(sig, it.sig):
                    if fullness(sig) > fullness(it.sig):          # пришло более полное имя — оно станет основным
                        old_form = person_form(it.sig)
                        if old_form:
                            it.forms[old_form] = it.value
                        it.value, it.sig = val, {**it.sig, **sig}
                    form = person_form(sig) if fullness(sig) < fullness(it.sig) else ""
                    if form:
                        it.forms.setdefault(form, val)
                    if e.text not in it.variants:
                        it.variants.append(e.text)
                    tok = it.token if not form else it.token[:-1] + f".{form}]"
                    self.by_key[key] = tok
                    return tok
        label = LABELS[e.kind]
        n = self.counters.get(label, 0) + 1
        self.counters[label] = n
        tok = f"[{label}_{n}]"
        # ФИО возвращаем в именительном падеже; места — как были написаны («по Пермскому краю»)
        value = e.normal if (e.kind == "PER" and e.normal) else e.text
        sig = person_signature(value) if e.kind == "PER" else {}
        self.items[tok] = Item(tok, e.kind, value, [e.text], sig)
        self.by_key[key] = tok
        return tok

    def anonymize(self, text: str, ner: NatashaNER | None = None,
                  custom_words: list[str] | None = None,
                  manual: list[str] | None = None) -> tuple[str, list[Entity]]:
        ents = find_regex(text)
        if ner is not None:
            ents += ner.find(text)
        ents += find_custom(text, (custom_words or []) + self.manual + (manual or []))
        vocab = ner._parts["vocab"] if (ner is not None and ner.ready) else None
        trimmed = []
        for e in ents:
            if e.kind == "PER" and e.source != "dict":
                e = trim_person(e, vocab)
            if e is not None:
                trimmed.append(e)
        ents = resolve_overlaps(trimmed)
        for e in ents:
            # Natasha иногда портит фамилии («Шпаков» → «Шпак»), поэтому ФИО с отчеством
            # нормализуем своими правилами по исходному тексту
            if e.kind == "PER" and any(is_patronymic(w) for w in e.text.split()[1:]):
                e.normal = normalize_fio(e.text, vocab)
            elif e.kind == "PER" and (not e.normal or "." in e.text):
                # с инициалами пол не определить: «Гусейнова Л.Р.» оставляем как есть
                e.normal = e.text

        parts, pos = [], 0
        for e in ents:
            parts.append(text[pos:e.start])
            tok = self._token_for(e)
            if e.kind == "PER":
                case = detect_case(e.text, vocab)
                if case:
                    tok = tok[:-1] + f"|{case}]"
            parts.append(tok)
            pos = e.end
        parts.append(text[pos:])
        return "".join(parts), ents

    # ------------------------------------------------------------ возврат
    def _lookup(self, label: str, num: str, form: str | None = None) -> tuple[Item, str] | None:
        label = label.upper().replace("СЧЕТ", "СЧЁТ")
        it = self.items.get(f"[{label}_{int(num)}]")
        if it is None:
            return None
        if not form:
            return it, it.value
        form = form.upper()
        if form in it.forms:
            return it, it.forms[form]
        # Нейросеть сама придумала форму («Уважаемый [ЧЕЛОВЕК_2.ИО]!») — строим её из полного ФИО
        w = it.value.split()
        if it.kind == "PER" and len(w) == 3:
            return it, (" ".join(w[1:]) if form == "ИО" else f"{w[0]} {w[1][0]}.{w[2][0]}.")
        return it, it.value

    def restore(self, text: str, ner: NatashaNER | None = None) -> tuple[str, int, list[str]]:
        """Возвращает (текст, сколько подставлено, метки без соответствия).
        Метки с падежом ([ЧЕЛОВЕК_1|рд]) склоняются. Позиции подстановок — в self.last_spans."""
        vocab = ner._parts["vocab"] if (ner is not None and ner.ready) else None
        missing: list[str] = []
        count = 0
        out, pos, spans = [], 0, []
        for m in RE_TOKEN.finditer(text):
            label = m.group("l1") or m.group("l2")
            num = m.group("n1") or m.group("n2")
            form = m.group("f1") or m.group("f2")
            case = normalize_case(m.group("c1"))
            found = self._lookup(label, num, form)
            out.append(text[pos:m.start()])
            pos = m.end()
            if found is None:
                missing.append(m.group(0))
                out.append(m.group(0))
                continue
            it, value = found
            if it.kind == "PER":
                # Нейросеть не всегда ставит падеж (или копирует чужой) — подстраховываемся контекстом
                guess, sure = infer_case(text[:m.start()], vocab)
                if guess and (sure or not case):
                    case = guess
            if case and it.kind == "PER":
                value = decline_person(value, case, vocab, gender_of(it.value.split()))
            elif case and it.kind == "LOC":
                value = decline_place(value, case, vocab)
            start = sum(len(x) for x in out)
            out.append(value)
            spans.append((start, start + len(value)))
            count += 1
        out.append(text[pos:])
        self.last_spans = spans
        return "".join(out), count, missing

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
