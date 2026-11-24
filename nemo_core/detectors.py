"""Поиск чувствительных данных в тексте.

Два источника:
  * шаблоны (регулярные выражения) — ИНН, СНИЛС, ОГРН, счета, карты, телефоны,
    почта, паспорт, юрлица в кавычках, ФИО с инициалами;
  * Natasha (локальная NER-модель) — ФИО, организации, адреса/места.

Natasha необязательна: если её нет, работают только шаблоны.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Типы сущностей → русская метка, которую увидит нейросеть.
LABELS = {
    "PER": "ЧЕЛОВЕК",
    "ORG": "ОРГАНИЗАЦИЯ",
    "LOC": "МЕСТО",
    "ADDR": "АДРЕС",
    "INN": "ИНН",
    "SNILS": "СНИЛС",
    "OGRN": "ОГРН",
    "KPP": "КПП",
    "BIK": "БИК",
    "ACCOUNT": "СЧЁТ",
    "CARD": "КАРТА",
    "PHONE": "ТЕЛЕФОН",
    "EMAIL": "EMAIL",
    "PASSPORT": "ПАСПОРТ",
    "CUSTOM": "СКРЫТО",
}

# Чем выше — тем важнее при пересечении найденных фрагментов.
PRIORITY = {
    "CUSTOM": 100,
    "EMAIL": 90, "CARD": 85, "ACCOUNT": 80, "PASSPORT": 80, "SNILS": 80,
    "OGRN": 78, "INN": 75, "KPP": 70, "BIK": 70, "PHONE": 70,
    "ADDR": 60, "ORG": 50, "PER": 45, "LOC": 30,
}


@dataclass
class Entity:
    start: int
    end: int
    kind: str
    text: str
    normal: str = ""          # нормальная форма (для ФИО/организаций)
    source: str = "regex"
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Ключ группировки: одинаковые сущности получают одну метку."""
        base = self.normal or self.text
        if self.kind in {"INN", "SNILS", "OGRN", "KPP", "BIK", "ACCOUNT", "CARD", "PHONE", "PASSPORT"}:
            base = re.sub(r"\D", "", base)
            if self.kind == "PHONE" and len(base) == 11 and base[0] in "78":
                base = "7" + base[1:]
        if self.kind == "ORG":
            # «ООО "Ромашка"», «ООО «Ромашка»» и «Ромашка» — одна организация
            base = re.sub(r"^(ООО|ОАО|ЗАО|ПАО|АО|НАО|НКО|АНО|ФГУП|МУП|ГУП|ГБУ|МБУ|ТОО|ЧУ)\s*", "", base)
            base = base.strip(QUOTES_OPEN + QUOTES_CLOSE + " ")
        return f"{self.kind}:{re.sub(r'\s+', ' ', base).strip().lower().replace('ё', 'е')}"


# ---------------------------------------------------------------- контрольные суммы

def _digits(s: str) -> list[int]:
    return [int(c) for c in s if c.isdigit()]


def inn_valid(s: str) -> bool:
    d = _digits(s)
    if len(d) == 10:
        w = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        return sum(a * b for a, b in zip(w, d)) % 11 % 10 == d[9]
    if len(d) == 12:
        w11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        w12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        c11 = sum(a * b for a, b in zip(w11, d)) % 11 % 10
        c12 = sum(a * b for a, b in zip(w12, d)) % 11 % 10
        return c11 == d[10] and c12 == d[11]
    return False


def snils_valid(s: str) -> bool:
    d = _digits(s)
    if len(d) != 11:
        return False
    total = sum(d[i] * (9 - i) for i in range(9))
    if total < 100:
        check = total
    elif total in (100, 101):
        check = 0
    else:
        check = total % 101
        if check == 100:
            check = 0
    return check == d[9] * 10 + d[10]


def ogrn_valid(s: str) -> bool:
    d = "".join(c for c in s if c.isdigit())
    if len(d) == 13:
        return int(d[:12]) % 11 % 10 == int(d[12])
    if len(d) == 15:
        return int(d[:14]) % 13 % 10 == int(d[14])
    return False


def luhn_valid(s: str) -> bool:
    d = _digits(s)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, x in enumerate(reversed(d)):
        if i % 2:
            x *= 2
            if x > 9:
                x -= 9
        total += x
    return total % 10 == 0


# ---------------------------------------------------------------- шаблоны

NB = r"(?<![\d\w])"   # нет цифры/буквы слева
NA = r"(?![\d\w])"    # нет цифры/буквы справа

RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zа-я]{2,}", re.I)
RE_SNILS = re.compile(NB + r"\d{3}[- ]?\d{3}[- ]?\d{3}[- ]?\d{2}" + NA)
RE_CARD = re.compile(NB + r"\d{4}(?:[ -]?\d{4}){2,3}(?:[ -]?\d{1,3})?" + NA)
RE_ACCOUNT = re.compile(NB + r"\d{5}[ .]?\d{3}[ .]?\d[ .]?\d{4}[ .]?\d{7}" + NA)  # 20 цифр
RE_OGRN = re.compile(NB + r"\d{13}(?:\d{2})?" + NA)
RE_INN = re.compile(NB + r"\d{10}(?:\d{2})?" + NA)
RE_KPP = re.compile(r"(КПП)\s*[:№]?\s*(\d{9})" + NA, re.I)
RE_BIK = re.compile(r"(БИК)\s*[:№]?\s*(\d{9})" + NA, re.I)
RE_INN_CTX = re.compile(r"(ИНН)\s*[:№]?\s*(\d{10}(?:\d{2})?)" + NA, re.I)
RE_PHONE = re.compile(
    NB + r"(?:\+7|8)[\s\-]*\(?\d{3}\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}" + NA
)
RE_PASSPORT = re.compile(
    r"(паспорт\w*[^\d\n]{0,40}?)(\d{2}\s?\d{2}\s?№?\s?\d{6})" + NA, re.I
)
QUOTES_OPEN = "«\"“„'"
QUOTES_CLOSE = "»\"”“'"
RE_ORG = re.compile(
    r"(?<![А-ЯЁа-яё])(?:ООО|ОАО|ЗАО|ПАО|АО|НАО|НКО|АНО|ФГУП|МУП|ГУП|ГБУ|МБУ|ТОО|ЧУ)\s*"
    r"[" + re.escape(QUOTES_OPEN) + r"][^" + re.escape(QUOTES_CLOSE) + r"\n]{1,80}["
    + re.escape(QUOTES_CLOSE) + r"]"
)
RE_IP = re.compile(
    r"(?<![А-ЯЁа-яё])ИП\s+[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
    r"(?:\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?|(?:\s+[А-ЯЁ][а-яё]+){1,2})?"
)
RE_ADDR = re.compile(
    r"(?<![А-ЯЁа-яё])(?:ул\.|улица|пр-т|просп\.|проспект|пер\.|переулок|бульвар|б-р|"
    r"шоссе|ш\.|наб\.|набережная|пл\.|площадь|мкр\.|микрорайон|тракт)\s*"
    r"[А-ЯЁ0-9][^,;\n]{1,40}"
    r"(?:,\s*(?:д\.|дом)\s*\d+[а-яА-Я]?(?:/\d+)?)?"
    r"(?:,\s*(?:кв\.|квартира|оф\.|офис|корп\.|корпус|стр\.|строение|пом\.)\s*\d+[а-яА-Я]?)*"
)
RE_FIO_INITIALS = re.compile(
    r"(?<![А-ЯЁа-яё])(?:[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]\."
    r"|[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)"
)


def find_regex(text: str) -> list[Entity]:
    out: list[Entity] = []

    def add(m_start, m_end, kind, extra=None):
        out.append(Entity(m_start, m_end, kind, text[m_start:m_end], extra=extra or {}))

    for m in RE_EMAIL.finditer(text):
        add(m.start(), m.end(), "EMAIL")
    for m in RE_PASSPORT.finditer(text):
        add(m.start(2), m.end(2), "PASSPORT")
    for rx, kind in ((RE_KPP, "KPP"), (RE_BIK, "BIK")):
        for m in rx.finditer(text):
            add(m.start(2), m.end(2), kind)
    for m in RE_INN_CTX.finditer(text):
        add(m.start(2), m.end(2), "INN")
    for m in RE_CARD.finditer(text):
        if luhn_valid(m.group()):
            add(m.start(), m.end(), "CARD")
    for m in RE_ACCOUNT.finditer(text):
        add(m.start(), m.end(), "ACCOUNT")
    for m in RE_SNILS.finditer(text):
        if snils_valid(m.group()):
            add(m.start(), m.end(), "SNILS")
    for m in RE_OGRN.finditer(text):
        if ogrn_valid(m.group()):
            add(m.start(), m.end(), "OGRN")
    for m in RE_INN.finditer(text):
        if inn_valid(m.group()):
            add(m.start(), m.end(), "INN")
    for m in RE_PHONE.finditer(text):
        add(m.start(), m.end(), "PHONE")
    for m in RE_ORG.finditer(text):
        add(m.start(), m.end(), "ORG")
    for m in RE_IP.finditer(text):
        add(m.start(), m.end(), "ORG")
    for m in RE_ADDR.finditer(text):
        add(m.start(), m.end(), "ADDR")
    for m in RE_FIO_INITIALS.finditer(text):
        add(m.start(), m.end(), "PER")
    return out


def find_custom(text: str, words: list[str]) -> list[Entity]:
    """Слова и фразы из словаря пользователя — скрываются всегда."""
    out = []
    for w in words:
        w = w.strip()
        if len(w) < 2:
            continue
        rx = re.compile(r"(?<![\w])" + re.escape(w) + r"(?![\w])", re.I)
        for m in rx.finditer(text):
            e = Entity(m.start(), m.end(), "CUSTOM", m.group(), normal=w, source="dict")
            out.append(e)
    return out


# ---------------------------------------------------------------- Natasha

# Слова, которые Natasha иногда принимает за организации, хотя это роли в документах.
STOP_WORDS = {
    "поставщик", "покупатель", "заказчик", "исполнитель", "подрядчик", "субподрядчик",
    "арендатор", "арендодатель", "продавец", "сторона", "стороны", "работодатель",
    "работник", "агент", "принципал", "доверитель", "поверенный", "лицензиар",
    "лицензиат", "заемщик", "заимодавец", "кредитор", "должник", "клиент", "банк",
    "устав", "приложение", "акт", "счет", "договор",
}


def _is_noise(kind: str, text: str) -> bool:
    t = text.strip(" «»\"'").lower().replace("ё", "е")
    if t in STOP_WORDS:
        return True
    first = t.split()[0] if t.split() else ""
    if kind == "ORG" and first in {"договор", "соглашение", "контракт", "акт", "приложение", "счет"}:
        return True
    return False


class NatashaNER:
    """Ленивая обёртка над Natasha. Загрузка занимает несколько секунд."""

    def __init__(self):
        self.ready = False
        self.error = ""
        self._parts = None

    def load(self) -> bool:
        try:
            from natasha import (Doc, MorphVocab, NewsEmbedding, NewsMorphTagger,
                                 NewsNERTagger, Segmenter)
            emb = NewsEmbedding()
            self._parts = dict(
                Doc=Doc, seg=Segmenter(), vocab=MorphVocab(),
                morph=NewsMorphTagger(emb), ner=NewsNERTagger(emb),
            )
            self.ready = True
        except Exception as e:  # нет пакета или сломалась модель
            self.error = repr(e)
            self.ready = False
        return self.ready

    def find(self, text: str) -> list[Entity]:
        if not self.ready:
            return []
        p = self._parts
        doc = p["Doc"](text)
        doc.segment(p["seg"])
        doc.tag_morph(p["morph"])
        doc.tag_ner(p["ner"])
        out = []
        for sp in doc.spans:
            if sp.type not in ("PER", "ORG", "LOC") or _is_noise(sp.type, sp.text):
                continue
            try:
                sp.normalize(p["vocab"])
                normal = sp.normal or sp.text
            except Exception:
                normal = sp.text
            out.append(Entity(sp.start, sp.stop, sp.type, sp.text, normal=normal, source="natasha"))
        return out


# ---------------------------------------------------------------- сведение

def resolve_overlaps(entities: list[Entity]) -> list[Entity]:
    """Оставляет непересекающиеся фрагменты: важнее тип, потом длиннее."""
    ranked = sorted(
        entities,
        key=lambda e: (-PRIORITY.get(e.kind, 0), -(e.end - e.start), e.start),
    )
    taken: list[Entity] = []
    for e in ranked:
        if all(e.end <= t.start or e.start >= t.end for t in taken):
            taken.append(e)
    return sorted(taken, key=lambda e: e.start)
