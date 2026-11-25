"""Склонение ФИО и мест при возврате данных.

Метка может нести падеж: [ЧЕЛОВЕК_1|рд] — «Белоусова Аркадия Геннадьевича».
Фамилии и отчества склоняем по правилам окончаний (словарь pymorphy их искажает),
имена и названия мест — по словарю pymorphy.
"""
from __future__ import annotations

import re

# Наши короткие обозначения ↔ граммемы pymorphy
CASES = {"им": "nomn", "рд": "gent", "дт": "datv", "вн": "accs", "тв": "ablt", "пр": "loct"}
GRAMMEME_TO_CASE = {v: k for k, v in CASES.items()}
# Что нейросеть может написать вместо короткого обозначения
CASE_ALIASES = {
    "им": "им", "имен": "им", "и": "им",
    "рд": "рд", "род": "рд", "р": "рд",
    "дт": "дт", "дат": "дт", "д": "дт",
    "вн": "вн", "вин": "вн", "в": "вн",
    "тв": "тв", "твор": "тв", "т": "тв",
    "пр": "пр", "пред": "пр", "п": "пр",
}
_ORDER = ["рд", "дт", "вн", "тв", "пр"]
_IDX = {c: i for i, c in enumerate(_ORDER)}


def normalize_case(raw: str | None) -> str | None:
    if not raw:
        return None
    r = raw.strip().lower().replace("ё", "е").rstrip(".")
    for k in (r, r[:4], r[:3], r[:2], r[:1]):
        if k in CASE_ALIASES:
            return CASE_ALIASES[k]
    return None


def _keep_caps(src: str, new: str) -> str:
    if src.isupper():
        return new.upper()
    if src[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def _ends(word: str, *endings: str) -> bool:
    return word.lower().endswith(endings)


# ---------------------------------------------------------------- фамилии

def decline_surname(word: str, case: str, gender: str | None) -> str:
    if case == "им":
        return word
    w, i = word, _IDX[case]
    if "-" in w:   # двойные фамилии: склоняем каждую часть
        return "-".join(decline_surname(p, case, gender) for p in w.split("-"))
    if _ends(w, "ский", "цкий"):
        return w[:-2] + ["ого", "ому", "ого", "им", "ом"][i]
    if _ends(w, "ская", "цкая"):
        return w[:-2] + ["ой", "ой", "ую", "ой", "ой"][i]
    if _ends(w, "ова", "ева", "ёва", "ина", "ына") and gender != "masc":
        return w[:-1] + ["ой", "ой", "у", "ой", "ой"][i]
    if _ends(w, "ов", "ев", "ёв", "ин", "ын") and gender != "femn":
        return w + ["а", "у", "а", "ым", "е"][i]
    if _ends(w, "о", "е", "и", "у", "ю", "ых", "их", "ко"):
        return w                                   # Ткаченко, Черных — не склоняются
    if _ends(w, "а", "я"):
        stem = w[:-1]
        if _ends(w, "я"):
            return stem + ["и", "е", "ю", "ей", "е"][i]
        soft = w[-2:-1].lower() in "гкхжшчщ"
        return stem + ["и" if soft else "ы", "е", "у", "ой", "е"][i]
    if gender == "femn":
        return w                                   # женские на согласный не склоняются
    if re.search(r"[бвгджзклмнпрстфхцчшщ]$", w.lower()):
        sib = w[-1].lower() in "жшчщц"
        return w + ["а", "у", "а", "ем" if sib else "ом", "е"][i]
    return w


# ---------------------------------------------------------------- отчества

def decline_patronymic(word: str, case: str) -> str:
    if case == "им":
        return word
    i = _IDX[case]
    if _ends(word, "вна", "чна", "ична"):
        return word[:-1] + ["ы", "е", "у", "ой", "е"][i]
    if _ends(word, "ич"):
        return word + ["а", "у", "а", "ем", "е"][i]
    return word


# ---------------------------------------------------------------- имена и места (словарь)

def _raw_parse(vocab, word):
    import pymorphy2
    return pymorphy2.MorphAnalyzer.parse(vocab, word)


def _lexeme_form(vocab, word: str, case: str, prefer: str | None = None,
                 gender: str | None = None) -> str | None:
    try:
        parses = _raw_parse(vocab, word.lower())
    except Exception:
        return None
    if prefer:
        parses = [p for p in parses if prefer in p.tag] or parses
    if gender:
        parses = [p for p in parses if p.tag.gender in (gender, None) or "ms-f" in p.tag] or parses
    g = CASES[case]
    for p in parses[:1]:
        number = p.tag.number or "sing"
        for f in p.lexeme:
            if g in f.tag and number in f.tag and (not p.tag.gender or f.tag.gender in (p.tag.gender, None)):
                return _keep_caps(word, f.word)
    return None


def decline_name(word: str, case: str, gender: str | None, vocab=None) -> str:
    if case == "им":
        return word
    if vocab is not None:
        f = _lexeme_form(vocab, word, case, prefer="Name", gender=gender)
        if f:
            return f
    # запасной вариант — как существительное
    return decline_surname(word, case, gender) if gender != "femn" or _ends(word, "а", "я") else word


def gender_of(words: list[str]) -> str | None:
    for w in words:
        if _ends(w, "вна", "чна", "вны", "вне", "вну", "вной", "чны", "чне", "чну", "чной"):
            return "femn"
        if re.search(r"(вич|ич)(а|у|ем|е)?$", w.lower()):
            return "masc"
    if words and _ends(words[0], "ова", "ева", "ина", "ская", "цкая"):
        return "femn"
    return None


def _is_initials(w: str) -> bool:
    return "." in w


def _looks_like_name(w: str, vocab) -> bool:
    if vocab is None:
        return False
    try:
        return any("Name" in p.tag for p in _raw_parse(vocab, w.lower()))
    except Exception:
        return False


def decline_person(value: str, case: str | None, vocab=None, gender: str | None = None) -> str:
    """«Белоусов Аркадий Геннадьевич» + «рд» → «Белоусова Аркадия Геннадьевича».
    Понимает «Аркадий Геннадьевич», «Кира Лебедева», «Белоусов А.Г.», «А.Г. Белоусов»."""
    if not case or case == "им":
        return value
    words = value.split()
    gender = gender or gender_of(words)
    plain = [w for w in words if not _is_initials(w)]
    roles: dict[int, str] = {}
    patr_last = len(words) >= 2 and re.search(r"(вич|вна|ична|чна|ич)$", words[-1].lower())
    if len(words) == 3 and not any(_is_initials(w) for w in words):
        roles = {0: "surn", 1: "name", 2: "patr"}
    elif len(words) == 2 and patr_last:
        roles = {0: "name", 1: "patr"}
    elif len(words) == 2 and not any(_is_initials(w) for w in words):
        roles = {0: "name", 1: "surn"} if _looks_like_name(words[0], vocab) else {0: "surn", 1: "name"}
    else:
        roles = {i: ("init" if _is_initials(w) else "surn") for i, w in enumerate(words)}
    if gender is None and len(plain) >= 1:
        name_idx = [i for i, r in roles.items() if r == "name"]
        if name_idx and vocab is not None:
            try:
                g = [p.tag.gender for p in _raw_parse(vocab, words[name_idx[0]].lower()) if "Name" in p.tag]
                gender = g[0] if g else None
            except Exception:
                pass
    out = []
    for i, w in enumerate(words):
        r = roles.get(i, "surn")
        if r == "init":
            out.append(w)
        elif r == "patr":
            out.append(decline_patronymic(w, case))
        elif r == "name":
            out.append(decline_name(w, case, gender, vocab))
        else:
            out.append(decline_surname(w, case, gender))
    return " ".join(out)


def decline_place(value: str, case: str | None, vocab=None) -> str:
    """«Пермский край» + «пр» → «Пермском крае». Если словарь не знает слово — оставляем."""
    if not case or vocab is None:
        return value
    out = []
    for w in value.split():
        if not re.match(r"[А-ЯЁа-яё]", w):
            out.append(w)
            continue
        f = _lexeme_form(vocab, w, case, prefer="Geox")
        out.append(f or w)
    return " ".join(out)


# ---------------------------------------------------------------- определение падежа в тексте

def detect_case(text: str, vocab) -> str | None:
    """Падеж упоминания человека в исходном тексте. None — именительный или неясно."""
    if vocab is None:
        return None
    words = [w for w in text.split() if not re.fullmatch(r"(?:[А-ЯЁ]\.\s?){1,2}", w)]
    if not words:
        return None
    common = None
    for w in words:
        cases = set()
        try:
            for p in _raw_parse(vocab, w.lower()):
                if "plur" in p.tag:
                    continue
                if p.tag.case and ({"Name", "Surn", "Patr"} & set(str(p.tag).replace(" ", ",").split(","))
                                   or p.tag.POS == "NOUN"):
                    cases.add(p.tag.case)
        except Exception:
            return None
        if not cases:
            continue
        if any(c.startswith("gen") for c in cases):
            cases.add("gent")
        if any(c.startswith("loc") for c in cases):
            cases.add("loct")
        common = cases if common is None else common & cases
    if not common or "nomn" in common:
        return None
    for g in ("gent", "datv", "accs", "ablt", "loct"):
        if g in common:
            return GRAMMEME_TO_CASE[g]
    return None


# ---------------------------------------------------------------- падеж по соседнему слову

# Предлоги, которые перед человеком однозначно задают падеж
PREP_CASE = {
    "с": "тв", "со": "тв", "к": "дт", "ко": "дт", "о": "пр", "об": "пр", "обо": "пр", "при": "пр",
    "у": "рд", "от": "рд", "для": "рд", "без": "рд", "до": "рд", "из": "рд", "около": "рд",
    "против": "рд", "кроме": "рд", "среди": "рд", "после": "рд", "вместо": "рд", "по": "дт",
}
# Должности и роли: имя после них стоит в том же падеже («директора Белоусова», «бухгалтеру Ткаченко»)
TITLES = {
    "директор", "руководитель", "бухгалтер", "менеджер", "сотрудник", "работник", "специалист",
    "инженер", "юрист", "представитель", "гражданин", "гражданка", "господин", "госпожа", "коллега",
    "заместитель", "председатель", "предприниматель", "начальник", "глава", "клиент", "заемщик",
    "должник", "сметчик", "администратор", "секретарь", "кассир", "врач", "пациент", "студент",
    "получатель", "отправитель", "плательщик", "собственник", "владелец", "наниматель", "арендатор",
}
_STOP_PUNCT = re.compile(r"[,:;!?()«»\"—–\-\n./|_\]]\s*$")


def infer_case(prefix: str, vocab) -> tuple[str | None, bool]:
    """Падеж метки по тексту перед ней. Возвращает (падеж, однозначно_ли).
    Однозначный (предлог) перекрывает падеж, который поставила нейросеть."""
    if vocab is None or not prefix.strip() or _STOP_PUNCT.search(prefix):
        return None, False
    # смотрим только на слово вплотную перед меткой (не через знаки, переносы и другие метки)
    tail = re.search(r"((?:[А-Яа-яЁё]+[ \t]+){1,2})$", prefix[-60:])
    if not tail:
        return None, False
    words = tail.group(1).split()
    last = words[-1].lower()
    if last in PREP_CASE:
        return PREP_CASE[last], True
    if last == "ип" and len(words) >= 2 and words[-2].lower() in PREP_CASE:
        return PREP_CASE[words[-2].lower()], True
    try:
        parses = [p for p in _raw_parse(vocab, last) if "plur" not in p.tag] or _raw_parse(vocab, last)
    except Exception:
        return None, False
    if not parses:
        return None, False
    p = parses[0]
    if p.tag.POS != "NOUN" or not p.tag.case:
        return None, False
    if p.normal_form in TITLES:
        g = p.tag.case
        g = "gent" if g.startswith("gen") else "loct" if g.startswith("loc") else g
        return GRAMMEME_TO_CASE.get(g), False
    return "рд", False          # «полномочия [Ч]», «предложением [Ч]» — родительный
