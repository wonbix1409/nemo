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
    assert masked.count("[ЧЕЛОВЕК_1") == 2             # падежи сведены в одну метку
    assert "[ЧЕЛОВЕК_1|рд]" in masked and "[ЧЕЛОВЕК_2|тв]" in masked   # падеж записан в метку
    restored, _, _ = s.restore("[ЧЕЛОВЕК_1] и [ЧЕЛОВЕК_2]")
    assert restored == "Иванов Иван Петрович и Петрова Анна"


def test_fio_on_own_line_and_noise(ner):
    s = Session()
    masked, _ = s.anonymize(
        "РЕЗЮМЕ\n\nМиронов Святослав Игоревич\n\nЖелаемая должность: сметчик. "
        "Согласование КС-2 и КС-3. Шпаков подписал акт.", ner=ner)
    assert "Миронов" not in masked and "Шпаков" not in masked   # ФИО и редкая фамилия скрыты
    assert "Желаемая" in masked and "КС-3" in masked            # обычные слова и формы не тронуты


def test_same_person_forms(ner):
    s = Session()
    t = ("в лице директора Белоусова Аркадия Геннадьевича. Подписал Белоусов А.Г. "
         "Звоните Аркадию Геннадьевичу. Подпись: А.Г. Белоусов")
    masked, _ = s.anonymize(t, ner=ner)
    assert "Белоусов" not in masked and "Аркади" not in masked
    assert "[ЧЕЛОВЕК_2" not in masked                               # один человек — один номер
    assert "[ЧЕЛОВЕК_1.ИО|дт]" in masked and "[ЧЕЛОВЕК_1.ИНИЦ]" in masked
    out, _, _ = s.restore("[ЧЕЛОВЕК_1], [ЧЕЛОВЕК_1.ИО], [ЧЕЛОВЕК_1.ИНИЦ]")
    assert out == "Белоусов Аркадий Геннадьевич, Аркадий Геннадьевич, Белоусов А.Г."


def test_surnames_not_damaged(ner):
    s = Session()
    s.anonymize("Шпакова Дмитрия Олеговича, Корниловой Вероники Андреевны, "
                "Исмаилова Руслана Маратовича", ner=ner)
    vals = sorted(it.value for it in s.items.values())
    assert vals == ["Исмаилов Руслан Маратович", "Корнилова Вероника Андреевна",
                    "Шпаков Дмитрий Олегович"]


def test_ogrn_not_card_and_public_bodies(ner):
    s = Session()
    masked, _ = s.anonymize("ОГРН 1093208196729. Паспорт выдан ГУ МВД России по Пермскому краю. "
                            "Гражданин РФ. Обратимся в Арбитражный суд.", ner=ner)
    assert "[ОГРН_1]" in masked and "КАРТА" not in masked
    for w in ("МВД", "России", "РФ", "Арбитражный суд"):
        assert w in masked, w


def test_ip_keeps_prefix(ner):
    s = Session()
    masked, _ = s.anonymize("Получатель: ИП Гусейнова Лейла Рашидовна. Подпись: Гусейнова Л.Р.", ner=ner)
    assert "ИП [ЧЕЛОВЕК_1]" in masked and "[ЧЕЛОВЕК_1.ИНИЦ]" in masked


def test_derived_forms_and_initials_gender(ner):
    s = Session()
    s.anonymize("Должник: Захарьин Тимофей Павлович. Подпись: ИП Гусейнова Л.Р.", ner=ner)
    out, _, _ = s.restore("Уважаемый [ЧЕЛОВЕК_1.ИО]! Ответственный: [ЧЕЛОВЕК_1.ИНИЦ], [ЧЕЛОВЕК_2]")
    assert out == "Уважаемый Тимофей Павлович! Ответственный: Захарьин Т.П., Гусейнова Л.Р."



def test_declension_on_restore(ner):
    s = Session()
    s.anonymize("Белоусов Аркадий Геннадьевич, Гусейнова Лейла Рашидовна, Ткаченко Ольга Владимировна. "
                "Город Пермь.", ner=ner)
    out, n, _ = s.restore("полномочия [ЧЕЛОВЕК_1|рд], передать [ЧЕЛОВЕК_2|дт], "
                          "согласовано с [ЧЕЛОВЕК_3|тв], звоните [ЧЕЛОВЕК_1.ИО|дт], "
                          "подписано [ЧЕЛОВЕК_1.ИНИЦ|тв], офис в [МЕСТО_1|пр]", ner=ner)
    assert out == ("полномочия Белоусова Аркадия Геннадьевича, передать Гусейновой Лейле Рашидовне, "
                   "согласовано с Ткаченко Ольгой Владимировной, звоните Аркадию Геннадьевичу, "
                   "подписано Белоусовым А.Г., офис в Перми")
    assert len(s.last_spans) == n == 6


def test_case_aliases(ner):
    s = Session()
    s.anonymize("Миронов Святослав Игоревич", ner=ner)
    out, _, _ = s.restore("[ЧЕЛОВЕК_1|род], [ЧЕЛОВЕК_1 | Р.п.], [ЧЕЛОВЕК_1|твор]", ner=ner)
    assert out == "Миронова Святослава Игоревича, Миронова Святослава Игоревича, Мироновым Святославом Игоревичем"


def test_round_trip_keeps_original_case(ner):
    s = Session()
    t = "в лице директора Белоусова Аркадия Геннадьевича и Петровой Анны Сергеевны"
    masked, _ = s.anonymize(t, ner=ner)
    assert s.restore(masked, ner=ner)[0] == t


def test_case_from_context(ner):
    s = Session()
    s.anonymize("Белоусов Аркадий Геннадьевич, Ткаченко Ольга Владимировна, ИП Гусейнова Лейла Рашидовна", ner=ner)
    ans = ("Согласен с предложением [ЧЕЛОВЕК_1.ИО]. Свяжитесь напрямую с [ЧЕЛОВЕК_1.ИО|дт]. "
           "Передайте главному бухгалтеру [ЧЕЛОВЕК_2]. Счёт от ИП [ЧЕЛОВЕК_3]. "
           "Добрый день, [ЧЕЛОВЕК_1.ИО]! Директор [ЧЕЛОВЕК_1] подписал.")
    out, _, _ = s.restore(ans, ner=ner)
    assert out == ("Согласен с предложением Аркадия Геннадьевича. Свяжитесь напрямую с Аркадием Геннадьевичем. "
                   "Передайте главному бухгалтеру Ткаченко Ольге Владимировне. Счёт от ИП Гусейновой Лейлы Рашидовны. "
                   "Добрый день, Аркадий Геннадьевич! Директор Белоусов Аркадий Геннадьевич подписал.")


def test_case_context_ignores_tokens_and_signature_lines(ner):
    s = Session()
    s.anonymize("ООО «Ромашка», директор Белоусов Аркадий Геннадьевич", ner=ner)
    out, _, _ = s.restore("Генеральный директор\n[ОРГАНИЗАЦИЯ_1]\n________ / [ЧЕЛОВЕК_1.ИО] /\n"
                          "[ОРГАНИЗАЦИЯ_1] [ЧЕЛОВЕК_1]", ner=ner)
    assert out.endswith("/ Аркадий Геннадьевич /\nООО «Ромашка» Белоусов Аркадий Геннадьевич")


# ---------------------------------------------------------------- 152-ФЗ: ключ и косвенные данные

def test_optional_dates_and_money_off_by_default():
    s = Session()
    text = "Договор от 05.03.2026 г., цена 1 250 000,00 руб., п. 3.1.12."
    masked, _ = s.anonymize(text)
    assert masked == text


def test_optional_dates_and_money_round_trip():
    s = Session()
    text = ("Договор от «12» марта 2026 года. Цена 120 000 (сто двадцать тысяч) рублей 00 копеек, "
            "аванс 500 ₽ до 05.03.2026 г. См. п. 3.1.12, 15 сотрудников.")
    masked, ents = s.anonymize(text, optional={"DATE", "MONEY"})
    assert "[ДАТА_1]" in masked and "[СУММА_1]" in masked
    assert "2026" not in masked and "рубл" not in masked
    assert "3.1.12" in masked and "15 сотрудников" in masked
    assert s.restore(masked)[0] == text


def test_session_file_is_sealed_and_loads(tmp_path):
    from nemo_core import vault
    s = Session()
    s.anonymize("ИНН 7707083893, почта ivanov@example.ru")
    p = tmp_path / "k" / "session.nemo"
    s.save(p)
    raw = p.read_bytes()
    assert raw.startswith((vault.HDR_DPAPI, vault.HDR_PLAIN))
    assert b"7707083893" not in raw and b"ivanov" not in raw   # даже без DPAPI не лежит открытым текстом
    s2 = Session.load(p)
    assert s2.restore("[ИНН_1], [EMAIL_1]")[0] == "7707083893, ivanov@example.ru"
    Session.wipe(p)
    assert not p.exists()


def test_legacy_plain_json_session_loads(tmp_path):
    import json
    s = Session()
    s.anonymize("ИНН 7707083893")
    p = tmp_path / "session.json"
    p.write_text(json.dumps(s.to_dict(), ensure_ascii=False), encoding="utf-8")
    assert Session.load(p).restore("[ИНН_1]")[0] == "7707083893"


def test_session_age():
    s = Session()
    s.updated -= 8 * 86400
    assert s.age_days() > 7


def test_settings_and_journal_have_no_values(tmp_path):
    from nemo_core.settings import Settings, journal_write
    st = Settings(optional_kinds=["DATE", "BAD"], session_ttl_days=3, journal=True)
    st.save(tmp_path / "settings.json")
    st2 = Settings.load(tmp_path / "settings.json")
    assert st2.optional_kinds == ["DATE"] and st2.session_ttl_days == 3
    assert st2.session_path(tmp_path).name == "session.nemo"
    s = Session()
    _, ents = s.anonymize("ИНН 7707083893, тел. +7 912 345-67-89")
    j = tmp_path / "journal.csv"
    journal_write(j, "скрытие", [e.kind for e in ents])
    body = j.read_text(encoding="utf-8-sig")
    assert "INN=1" in body and "PHONE=1" in body
    assert "7707083893" not in body and "345-67-89" not in body


def test_abbreviation_before_name_keeps_nominative(ner):
    for t in ("Получатель: ИП Гусейнова Лейла Рашидовна", "и гражданин РФ Миронов Святослав Игоревич"):
        s = Session()
        masked, _ = s.anonymize(t, ner=ner)
        assert s.restore(masked, ner=ner)[0] == t


def test_money_does_not_eat_sentence_period():
    from nemo_core.detectors import find_optional
    assert [e.text for e in find_optional("на сумму 4 870 500 рублей.", {"MONEY"})] == ["4 870 500 рублей"]
    assert [e.text for e in find_optional("цена 1 250 000,00 руб. итого", {"MONEY"})] == ["1 250 000,00 руб."]
