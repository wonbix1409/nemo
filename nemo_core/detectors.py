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
    "DATE": "ДАТА",
    "MONEY": "СУММА",
    "CUSTOM": "СКРЫТО",
}

# Косвенные данные: по ним человека можно узнать вместе с контекстом, но нейросети они
# часто нужны для работы (сроки, суммы). Поэтому скрываются только по выбору пользователя.
OPTIONAL_KINDS = ("DATE", "MONEY")

# Чем выше — тем важнее при пересечении найденных фрагментов.
PRIORITY = {
    "CUSTOM": 100,
    "EMAIL": 90, "CARD": 85, "ACCOUNT": 80, "PASSPORT": 80, "SNILS": 80,
    "OGRN": 78, "INN": 75, "KPP": 70, "BIK": 70, "PHONE": 70,
    "MONEY": 66, "DATE": 65,
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
    if not 16 <= len(d) <= 19:
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
RE_CARD = re.compile(NB + r"\d{4}(?:[ -]?\d{4}){3}(?:[ -]?\d{1,3})?" + NA)   # 16–19 цифр
RE_ACCOUNT = re.compile(NB + r"\d{5}[ .]?\d{3}[ .]?\d[ .]?\d{4}[ .]?\d{7}" + NA)  # 20 цифр
RE_OGRN = re.compile(NB + r"\d{13}(?:\d{2})?" + NA)
RE_INN = re.compile(NB + r"\d{10}(?:\d{2})?" + NA)
RE_KPP = re.compile(r"(КПП)\s*[:№]?\s*(\d{9})" + NA, re.I)
RE_BIK = re.compile(r"(БИК)\s*[:№]?\s*(\d{9})" + NA, re.I)
RE_OGRN_CTX = re.compile(r"(ОГРНИП|ОГРН)\s*[:№]?\s*(\d{13}(?:\d{2})?)" + NA, re.I)
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
    r"(?<![А-ЯЁа-яё])(?:ул\.|улица|пр-т|просп\.|пр\.|проспект|пер\.|переулок|бульвар|б-р|"
    r"шоссе|ш\.|наб\.|набережная|пл\.|площадь|мкр\.|микрорайон|тракт)\s*"
    r"[А-ЯЁ0-9][^,;\n]{1,40}"
    r"(?:,\s*(?:д\.|дом)\s*\d+[а-яА-Я]?(?:/\d+)?)?"
    r"(?:,\s*(?:кв\.|квартира|оф\.|офис|корп\.|корпус|стр\.|строение|пом\.)\s*\d+[а-яА-Я]?)*"
)
# Фамилия Имя Отчество в любом падеже — отчество узнаём по окончанию (-вич/-вна/-ична…)
RE_FIO_FULL = re.compile(
    r"(?<![А-ЯЁа-яё])[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ][а-яё]+\s+"
    r"[А-ЯЁ][а-яё]+(?:вич|вн|ичн)[а-яё]{0,3}(?![А-ЯЁа-яё])"
)
RE_FIO_INITIALS = re.compile(
    r"(?<![А-ЯЁа-яё])(?:[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]\."
    r"|[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)"
)

_MONTHS = r"(?:январ|феврал|март|апрел|ма|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-яё]*"
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
_YEAR_TAIL = r"(?:\s*(?:г\.|гг\.|года?|году))?"
# 05.03.2026, 5.3.2026 г. — год только из 4 цифр, чтобы не задеть номера пунктов «3.1.12»
RE_DATE_NUM = re.compile(NB + _DAY + r"\.(?:0?[1-9]|1[0-2])\.(?:19|20)\d{2}" + NA + _YEAR_TAIL)
# «05» марта 2026 г., 5 марта 2026 года
RE_DATE_TXT = re.compile(r"(?<![\w])[«\"]?" + _DAY + r"[»\"]?\s+" + _MONTHS + r"\s+(?:19|20)\d{2}"
                         + NA + _YEAR_TAIL, re.I)
_NUM = r"\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_CUR = r"(?:руб(?:л[а-яё]*)?\.?|₽|р\.|долл[а-яё]*\.?|USD|EUR|евро|\$|€)"
# 1 250 000,00 руб.; 120 000 (сто двадцать тысяч) рублей 00 копеек; 500 ₽
RE_MONEY = re.compile(
    NB + r"(?:" + _NUM + r")(?:\s*\([^()\n]{3,160}\))?\s*" + _CUR
    + r"(?:\s*\d{2}\s*коп(?:е[а-яё]*)?\.?)?", re.I)


def find_optional(text: str, kinds) -> list[Entity]:
    out: list[Entity] = []
    if "DATE" in kinds:
        for rx in (RE_DATE_NUM, RE_DATE_TXT):
            for m in rx.finditer(text):
                out.append(Entity(m.start(), m.end(), "DATE", m.group()))
    if "MONEY" in kinds:
        for m in RE_MONEY.finditer(text):
            out.append(Entity(m.start(), m.end(), "MONEY", m.group()))
    return out


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
    for m in RE_OGRN_CTX.finditer(text):
        add(m.start(2), m.end(2), "OGRN")
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
        # «ИП» оставляем видимым, скрываем человека: «ИП [ЧЕЛОВЕК_1]»
        name_start = m.start() + len(re.match(r"ИП\s+", m.group()).group())
        add(name_start, m.end(), "PER")
    for m in RE_ADDR.finditer(text):
        add(m.start(), m.end(), "ADDR")
    for m in RE_FIO_FULL.finditer(text):
        add(m.start(), m.end(), "PER")
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
    # страны не скрываем: они не указывают на человека, а метка сбивает нейросеть («гражданин [МЕСТО_2]»)
    "россия", "рф", "российская федерация",
    # госорганы и суды: публичные, а метки ломают фразы вроде «выдан [ОРГ] [ОРГ]»
    "мвд", "гу", "гу мвд", "уфмс", "оуфмс", "фмс", "фнс", "ифнс", "пфр", "сфр", "фсс", "гибдд",
    "фссп", "росреестр", "ип", "суд", "арбитражный суд", "районный суд", "мировой суд",
}


def _is_noise(kind: str, text: str, vocab=None) -> bool:
    t = text.strip(" «»\"'").lower().replace("ё", "е")
    if kind in ("ORG", "LOC") and any(c.isdigit() for c in t):
        return True          # «КС-3», «Приложение 1» — формы и номера, а не названия
    if kind == "PER" and vocab is not None and len(t.split()) == 1:
        # Одно слово с большой буквы («Желаемая»). Выбрасываем, только если это точно
        # не существительное: незнакомую фамилию лучше скрыть лишний раз, чем пропустить.
        try:
            parses = vocab.parse(t)
            top = parses[0].tag if parses else None
            names = any({"Name", "Surn", "Patr"} & set(str(p.tag).replace(" ", ",").split(","))
                        for p in parses)
            if top is not None and not names and top.POS in {
                    "ADJF", "ADJS", "PRTF", "PRTS", "VERB", "INFN", "ADVB", "PREP", "CONJ", "PRCL"}:
                return True
        except Exception:
            pass
    if t in STOP_WORDS:
        return True
    if vocab is not None and len(t.split()) <= 2:
        try:
            lemma = " ".join(vocab.parse(w)[0].normal for w in t.split()).replace("ё", "е")
            if lemma in STOP_WORDS:
                return True
        except Exception:
            pass
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
            if sp.type not in ("PER", "ORG", "LOC"):
                continue
            if "\n" in sp.text:
                # Модель иногда склеивает строки («Миронов С.И.\n\nЖелаемая») — режем по переносам
                pos = sp.start
                for part in sp.text.split("\n"):
                    lead = len(part) - len(part.lstrip())
                    chunk = part.strip()
                    if chunk and not _is_noise(sp.type, chunk, p["vocab"]):
                        a = pos + lead
                        out.append(Entity(a, a + len(chunk), sp.type, chunk, normal=chunk,
                                          source="natasha-split"))
                    pos += len(part) + 1
                continue
            if _is_noise(sp.type, sp.text, p["vocab"]):
                continue
            ip = re.match(r"ИП\s+(?=[А-ЯЁ])", sp.text)
            if sp.type == "ORG" and ip:
                a = sp.start + ip.end()
                out.append(Entity(a, sp.stop, "PER", text[a:sp.stop], source="natasha-ip"))
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
        key=lambda e: (-(PRIORITY.get(e.kind, 0) if PRIORITY.get(e.kind, 0) >= 60 else 40),
                       -(e.end - e.start), -PRIORITY.get(e.kind, 0), e.source != "natasha", e.start),
    )
    taken: list[Entity] = []
    for e in ranked:
        if all(e.end <= t.start or e.start >= t.end for t in taken):
            taken.append(e)
    return sorted(taken, key=lambda e: e.start)


# ---------------------------------------------------------------- ФИО: нормализация и подпись

_RE_PATR_M = re.compile(r"^(.+?(?:вич|ич))(?:а|у|ем|е)?$")
_RE_PATR_F = re.compile(r"^(.+?(?:вн|чн))(?:а|ы|е|ой|у|ою)$")


def is_patronymic(word: str) -> bool:
    w = word.lower()
    return bool(re.search(r"(?:вич|вн|ичн)[а-яё]{0,3}$", w)) and len(w) > 5


def _norm_patronymic(word: str) -> tuple[str, str | None]:
    """Отчество в именительный падеж по правилам — без словаря, чтобы не менять написание."""
    w = word
    m = _RE_PATR_F.match(w.lower())
    if m:
        return w[:len(m.group(1))] + "а", "femn"
    m = _RE_PATR_M.match(w.lower())
    if m:
        return w[:len(m.group(1))], "masc"
    return w, None


_RE_SURN = re.compile(r"^(.+?(?:ов|ев|ёв|ин|ын|ский|цкий))(а|у|ым|ом|е|ой|ую|ою|ого|ому|им)?$", re.I)


def _norm_surname(word: str, gender: str | None) -> str | None:
    """Фамилии на -ов/-ев/-ин/-ский — по правилам. None, если правило не подходит."""
    low = word.lower()
    if low.endswith(("ский", "цкий", "ская", "цкая")):
        return word
    m = re.match(r"^(.+?(?:ск|цк))(ого|ому|им|ом|ой|ую|ая)$", low)
    if m:
        base = word[:len(m.group(1))]
        return base + ("ая" if gender == "femn" else "ий")
    m = re.match(r"^(.+?(?:ов|ев|ёв|ин|ын))(а|у|ым|ом|е|ой|ою)?$", low)
    if not m:
        return None
    base = word[:len(m.group(1))]
    if gender == "femn":
        return base + "а"
    if gender == "masc":
        return base
    return word if m.group(2) in (None, "а") else base


def _raw_parse(vocab, word):
    import pymorphy2
    return pymorphy2.MorphAnalyzer.parse(vocab, word)


def _nomn(vocab, word: str, want: str, gender: str | None) -> str:
    """Имя в именительный падеж. Если словарь меняет основу — оставляем как было."""
    if vocab is None:
        return word
    try:
        parses = _raw_parse(vocab, word)
    except Exception:
        return word
    cand = [p for p in parses if want in p.tag] or parses
    for p in cand:
        for f in p.lexeme:
            t = f.tag
            if "nomn" in t and "plur" not in t and (gender is None or t.gender in (gender, None) or "ms-f" in t):
                new = f.word
                stem = len(word) - 3
                if new[:max(stem, 2)].lower() == word[:max(stem, 2)].lower() or len(word) <= 4:
                    return new[:1].upper() + new[1:]
                return word
    return word


def normalize_fio(text: str, vocab=None) -> str:
    """«Мироновым Святославом Игоревичем» → «Миронов Святослав Игоревич». Инициалы не трогаем."""
    words = text.split()
    if not words or any("." in w for w in words):
        return text
    if len(words) == 3 and is_patronymic(words[2]):
        patr, gender = _norm_patronymic(words[2])
        surn = _norm_surname(words[0], gender)
        if surn is None:   # Ткаченко, Гусейн-заде и пр. — несклоняемые или редкие: не трогаем
            surn = words[0]
        return " ".join([surn, _nomn(vocab, words[1], "Name", gender), patr])
    if len(words) == 2 and is_patronymic(words[1]):
        patr, gender = _norm_patronymic(words[1])
        return " ".join([_nomn(vocab, words[0], "Name", gender), patr])
    return text


def person_signature(name: str) -> dict:
    """Подпись человека для сведения вариантов: фамилия + инициалы (и полные имя/отчество, если есть)."""
    n = name.replace("ё", "е").replace("Ё", "Е").strip()
    m = re.fullmatch(r"([А-ЯЕ][а-яе-]+)\s+([А-ЯЕ])\.\s?([А-ЯЕ])\.?", n)
    if m:
        return dict(surn=m.group(1).lower(), i=m.group(2), o=m.group(3))
    m = re.fullmatch(r"([А-ЯЕ])\.\s?([А-ЯЕ])\.\s?([А-ЯЕ][а-яе-]+)", n)
    if m:
        return dict(surn=m.group(3).lower(), i=m.group(1), o=m.group(2))
    w = n.split()
    if len(w) == 3 and is_patronymic(w[2]):
        return dict(surn=w[0].lower(), i=w[1][0], o=w[2][0], name=w[1].lower(), patr=w[2].lower())
    if len(w) == 2 and is_patronymic(w[1]):
        return dict(i=w[0][0], o=w[1][0], name=w[0].lower(), patr=w[1].lower())
    return {}


def same_person(a: dict, b: dict) -> bool:
    if not a or not b or a.get("i") != b.get("i") or a.get("o") != b.get("o"):
        return False
    if a.get("surn") and b.get("surn"):
        sa, sb = a["surn"], b["surn"]
        # «Белоусов» / «Белоусова»: допускаем женскую форму той же фамилии
        if not (sa == sb or sa.rstrip("а") == sb.rstrip("а")):
            return False
        return all(a.get(k) == b.get(k) for k in ("name", "patr") if a.get(k) and b.get(k))
    # «Аркадий Геннадьевич» без фамилии — совпадают полные имя и отчество
    return bool(a.get("name") and a.get("name") == b.get("name") and a.get("patr") == b.get("patr"))


def fullness(sig: dict) -> int:
    return (2 if sig.get("surn") else 0) + (1 if sig.get("name") else 0)


_NON_NAME_POS = {"VERB", "INFN", "ADVB", "PREP", "CONJ", "PRCL", "INTJ", "ADJF", "ADJS", "PRTF", "GRND", "NPRO"}


def trim_person(e: Entity, vocab) -> Entity | None:
    """Срезает с краёв ФИО слова, которые точно не имена: «Звоните Аркадию Геннадьевичу» → «Аркадию Геннадьевичу»."""
    if vocab is None:
        return e
    tokens = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", e.text)]

    def not_name(w: str) -> bool:
        w = w.strip(".,;:!?«»\"()")
        if re.fullmatch(r"(?:[А-ЯЁ]\.\s?){1,2}", w + ("" if w.endswith(".") else ".")) and len(w) <= 4:
            return False                          # инициалы
        try:
            ps = _raw_parse(vocab, w.lower())
        except Exception:
            return False
        if any({"Name", "Surn", "Patr"} & set(str(p.tag).replace(" ", ",").split(",")) for p in ps):
            return False
        return bool(ps) and ps[0].tag.POS in _NON_NAME_POS

    while tokens and not_name(tokens[0][2]):
        tokens.pop(0)
    while tokens and not_name(tokens[-1][2]):
        tokens.pop()
    if not tokens:
        return None
    a, b = tokens[0][0], tokens[-1][1]
    if (a, b) == (0, len(e.text)):
        return e
    t = e.text[a:b]
    return Entity(e.start + a, e.start + b, e.kind, t, normal="", source=e.source)
