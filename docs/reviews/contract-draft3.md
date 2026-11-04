# Чекпоинт INTEGRATION-01B: canonical draft.3

Дата: 2026-11-04. Продолжены существующие Scout #3 / PR #4, без новых задач.
Вход: Scout draft.2 ref `547a343a462169461be3a5e33ea6766f83b5b988` и принятое
как требования предложение SkillForge PR #10 ref
`0fc2e8d96c6669782945e42bc78357d0aa4609ed` (4 positive / 33 negative).

**Реализовано: canonical формат и проверяемые fixture-последовательности draft.3.
Совместное принятие новой версии, runtime/адаптер/PoC не выполнены.**

| Замечание | Результат этой ревизии | Свидетельство |
| --- | --- | --- |
| R1 | Legal step3599 и terminal3600 проходят; clock/age/TTL/budget не ослаблены | Clock regression, full-budget trace, пять проверок допуска датчика |
| R2 | Active trial/epoch, segment/target/start/end, глобальный clock/budget, inspection-stop, terminal без drive | Late segment280..300, целая A→inspection→B→fault последовательность, replay/target/budget отрицательные случаи |
| R3 | Sensor/path/guard/stop-fault не становятся успехом; сохранена fail-closed семантика | Каждый safety fault, guard/stop и sensor/budget приоритеты |
| SCOUT-C1 | Закрытые 10 fault-кодов и двусторонняя status/reason таблица | Все несовместимые пары отвергаются независимо от состояния датчика |
| R4 | Полный manifest, digest/scene/profile/seed связи, raw/requested/applied/stop журнал, честный partial prefix | Полные и частичные fixtures, удаление provenance, подмена execution, выдуманные результаты/границы |

Изменены только contract docs/schema/examples, scripts и связанный workflow.
Пакеты scout/, vision, tests и simulator/mission runtime не меняются.

## Проверяемые артефакты

- [Нормативный проект](../integration/contract-v0.md), [схема](../integration/contract-v0.schema.json),
  [пять literal format reports](../integration/contract-v0.examples.json).
- [Исходный полный отчёт проверки](evidence/contract-draft3-check.json),
  [clock regression](evidence/contract-draft3-clock.json).
- Две длинные последовательности генерируются детерминированно; полный budget
  содержит 3600 advance и terminal observation3600. CLI сохраняет все семь
  базовых reports под runs/contract-fixtures; workflow публикует их как artifacts.
- Closure checker модулей и SHA-256 schema/examples перечислены в JSON.

Локальная среда: Linux / CPython3.12.14. Проверены canonical fixtures, clock,
30 core tests и четыре исходных demo outcome. Точность на реальных фото не
измерялась, CV к движению не подключается. Точные counts/digests берутся из
исходного JSON, а актуальный CI нового commit — из PR #4. Предыдущие зелёные
запуски не являются проверкой новой ревизии.

Набор measured-profile completeness существует только в памяти теста и явно
помечен форматной проверкой. Все сохранённые literal reports — contract_example,
source digests/environment намеренно null; никаких вымышленных измерений.
Данные provenance фиксируют claims; их подлинность без исходного исполнения
не аутентифицируется офлайн-checker.

## Следующая передача

SkillForge должен получить точный новый ref/digest и всю closure scripts, явно
сделать repin, повторить проверки и согласовать таблицу причин/partial reports.
Только после этого решается следующий runtime-этап с учётом открытой приёмки
цифрового Scout и настоящих фото SCOUT-02. Исторические pins SkillForge не
переписываются из Scout. Само наличие новых fixtures не закрывает issue #3,
продуктовый Gate1, ручную приёмку или оборудование.

Стек #1→#2→#4 сохраняется. Main, gh-pages, SkillForge и ветки #1/#2 не изменены;
merge, закупки и аппаратные испытания не выполняются.
