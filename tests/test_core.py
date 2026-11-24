import pytest

from nemo_core.anonymizer import Session
from nemo_core.detectors import (NatashaNER, find_regex, inn_valid, ogrn_valid,
                                 snils_valid)

# Реальные по формату, но публичные/тестовые номера
INN10 = "7707083893"      # ПАО Сбербанк
INN12 = "500100732259"
OGRN = "1027700132195"    # ПАО Сбербанк
SNILS = "112-233-445 95"


def test_checksums():
    assert inn_valid(INN10) and inn_valid(INN12)
    assert not inn_valid("7707083890")
    assert ogrn_valid(OGRN) and not ogrn_valid("1027700132190")
    assert snils_valid(SNILS) and not snils_valid("112-233-445 96")


def kinds(text):
    return sorted({e.kind for e in find_regex(text)})


def test_regex_kinds():
    t = (f"ИНН {INN10}, КПП 773601001, ОГРН {OGRN}, БИК 044525225, "
         f"р/с 40702810938000012345, тел. +7 (912) 345-67-89, почта ivanov@mail.ru, "
         f"СНИЛС {SNILS}, паспорт серия 57 08 № 123456, карта 4276 3800 1234 5678")
    found = kinds(t)
    for k in ["INN", "KPP", "OGRN", "BIK", "ACCOUNT", "PHONE", "EMAIL", "SNILS", "PASSPORT"]:
        assert k in found, k


def test_round_trip_and_same_token():
    s = Session()
    t = f"ООО «Ромашка» (ИНН {INN10}). Повторно: ИНН {INN10}, звонить 8 912 345 67 89 или +79123456789."
    masked, _ = s.anonymize(t)
    assert INN10 not in masked and "Ромашка" not in masked
    assert masked.count("[ИНН_1]") == 2
    assert masked.count("[ТЕЛЕФОН_1]") == 2          # один и тот же номер
    restored, n, missing = s.restore(masked)
    assert INN10 in restored and "Ромашка" in restored and not missing


def test_restore_tolerant():
    s = Session()
    s.anonymize(f"ИНН {INN10}, счёт 40702810938000012345")
    out, n, _ = s.restore("Проверь ИНН_1 и [СЧЕТ_1], а также [ инн 1 ]. Займи место 1.")
    assert out.count(INN10) == 2 and "40702810938000012345" in out
    assert "место 1" in out                           # обычный текст не тронут


def test_missing_token_reported():
    s = Session()
    _, n, missing = s.restore("Тут [ЧЕЛОВЕК_7]")
    assert n == 0 and missing == ["[ЧЕЛОВЕК_7]"]


def test_custom_dictionary():
    s = Session()
    masked, _ = s.anonymize("Проект Северный поток-3 стартует", custom_words=["Северный поток-3"])
    assert "Северный" not in masked and "[СКРЫТО_1]" in masked


def test_save_load(tmp_path):
    s = Session()
    s.anonymize(f"ИНН {INN10}")
    p = tmp_path / "s.json"
    s.save(p)
    s2 = Session.load(p)
    assert s2.restore("[ИНН_1]")[0] == INN10


@pytest.fixture(scope="module")
def ner():
    n = NatashaNER()
    if not n.load():
        pytest.skip("natasha не установлена")
    return n


def test_natasha_names_grouped(ner):
    s = Session()
    t = ("Договор между ООО «Ромашка» в лице директора Иванова Ивана Петровича "
         "и Петровой Анной. Иванов Иван Петрович подписывает. Адрес: город Пермь.")
    masked, _ = s.anonymize(t, ner=ner)
    assert "Иванов" not in masked and "Петров" not in masked and "Пермь" not in masked
    assert masked.count("[ЧЕЛОВЕК_1]") == 2            # падежи сведены в одну метку
    restored, _, _ = s.restore("[ЧЕЛОВЕК_1] и [ЧЕЛОВЕК_2]")
    assert restored == "Иванов Иван Петрович и Петрова Анна"


def test_fio_on_own_line_and_noise(ner):
    s = Session()
    masked, _ = s.anonymize(
        "РЕЗЮМЕ\n\nМиронов Святослав Игоревич\n\nЖелаемая должность: сметчик. "
        "Согласование КС-2 и КС-3. Шпаков подписал акт.", ner=ner)
    assert "Миронов" not in masked and "Шпаков" not in masked   # ФИО и редкая фамилия скрыты
    assert "Желаемая" in masked and "КС-3" in masked            # обычные слова и формы не тронуты
