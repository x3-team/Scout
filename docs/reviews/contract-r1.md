# Чекпоинт Scout: canonical-поправка R1, без runtime

Дата: 2026-11-04. Продолжение существующих #3 / draft PR #4.
**Реализовано и локально проверено: R1. Контракт, Gate 1 и продукты не объявлены
принятыми.** Никаких merge, закупок, запуска адаптера или изменений основного
кода Scout/SkillForge. Следующий контекст восстанавливать из этого документа,
[предыдущего ревью](current-prs.md) и текущих статусов GitHub.

## Восстановленный checkpoint

Сначала перечитаны Scout PR #1/#2/#4, issue #3/#5/#6 и их обсуждения; проверены
checks/status/workflow runs для точного head каждого PR, review submissions и
inline threads. Reviews/threads пусты, формального одобрения нет. Legacy commit
status без записей не считается ожидающим CI: фактические Actions check-runs
завершены success. На момент начала продолжения:

| Работа | Head | Автоматическое свидетельство | Остаётся |
| --- | --- | --- | --- |
| [#1](https://github.com/x3-team/Scout/pull/1), цифровой Scout | `e8ad8dfda3d4417c97f40bd7128377af2bb224a1` | [CI 41821088847](https://github.com/x3-team/Scout/actions/runs/41821088847), 5/5 success | Итоговая приёмка цифрового объёма владельцем |
| [#2](https://github.com/x3-team/Scout/pull/2), CPU vision | `03bff5eb0c93eb7a080f7a8840d350ad75e86c52` | [CI 41824917966](https://github.com/x3-team/Scout/actions/runs/41824917966), 9/9 success | Реальные фото и лабораторные метрики |
| [#4](https://github.com/x3-team/Scout/pull/4), проект контракта | `10817add66e15730f89599375132b2c08a4473f0` | [contract 41840469335](https://github.com/x3-team/Scout/actions/runs/41840469335), 2/2; [Scout 41840468882](https://github.com/x3-team/Scout/actions/runs/41840468882), 9/9 success | Ответ на SkillForge R1/R2/R4; договорённость о новой версии |

Стек остаётся #1 → #2 → #4. #5 фиксирует четыре продуктовых gate, семь
гипотез инспекции и discovery: 10–15 интервью в трёх сегментах. Никакой gate
не закрыт автоматически. #6 — исследование Desk Inspector, не разрешение
запустить третий dev-поток; его реализация здесь не начинается.

## Что изменено и почему

Изучен встречный [SkillForge PR #10](https://github.com/x3-team/SkillForge/pull/10),
ref `969ed414a761b701f21559ac68edcf9b7ac27b6b`. Использована уже подготовленная
[кандидатная delta R1](https://github.com/x3-team/SkillForge/blob/969ed414a761b701f21559ac68edcf9b7ac27b6b/docs/integration/r1-clock-candidate.patch),
а не новая конкурирующая схема или задача.

На шаге 3599 `step*0.05` даёт `179.95000000000002`; прежний структурный
maximum 179.95 отвергает правильный clock. Дефект воспроизведён на исходном
Scout schema/checker. В canonical [схеме](../integration/contract-v0.schema.json)
только два числовых maximum времени подняты до 180; версия схемы и четырёх
сообщений примера обновлена до `scout-skillforge/0.1-draft.2`.
Контекстные clock/age/TTL и бюджет шагов не ослаблены. Runtime не использует
этот draft; существующий pin draft.1 в SkillForge не переписывается молча.

## Проверяемый результат

Изолированная локальная копия сверена по всем 46 Git blob SHA исходного Scout
head `10817add…`; это snapshot, не upstream Git history. Linux / CPython 3.12.14.

```powershell
python scripts/check_integration_contract.py
python scripts/check_contract_clock.py --output runs/contract-clock-check.json
python -m unittest discover -s tests -v
python scripts/check_demos.py
```

- Прежние 6 положительных, 35 отрицательных и 7 strict/nonfinite проверок проходят.
- R1 воспроизведён со старыми пределами; все 3600 допустимых clock-step проходят
  новую ревизию. Ещё три положительных проверки возраста/допуска проходят.
- 13 новых отрицательных границ отвергнуты: clock=180, sample=180, clock drift,
  future/stale sensor, TTL, поздний/повторный/отрицательный/избыточный шаг,
  старая версия и полностью согласованный extra-step за бюджетом.
- 30 core tests и все четыре demo outcome проходят; код ядра не менялся.
  Vision локально повторно не запускался; его предыдущий CI указан выше.

Машиночитаемый [исходный отчёт](evidence/contract-clock-check.json) содержит digest
схемы/примеров, точные ref, границы и явные `contract_accepted=false`,
`runtime_adapter_executed=false`, `poc_executed=false`. Это вымышленные форматные
exchange, не измеренные маршруты. Workflow PR #4 теперь выполняет регрессию на
Windows/Linux и сохраняет отдельный JSON artifact. Актуальные CI и SHA поправки
должны быть сверены в PR #4: ссылки в таблице относятся к предыдущему head.

## Следующие условия, без повторного изобретения плана

R1 локально исправлено; совместное принятие новой ревизии ещё не получено.
R3 было устранено до этого продолжения и повторно не реализуется.

| Замечание | Следующий конкретный результат | Почему ещё открыто |
| --- | --- | --- |
| R2, сегменты / epoch | Следующая canonical-ревизия по [предложению SkillForge](https://github.com/x3-team/SkillForge/blob/969ed414a761b701f21559ac68edcf9b7ac27b6b/docs/integration/R2-R4-DECISIONS.md): уникальный epoch живой попытки, единый глобальный budget, segment/target ID, start/end step, advance[start,end), остановленная инспекция с motion_enabled=false | draft.2 пока не связывает результат с сегментом и интервалом; проверка metrics.steps >= observation.step для нескольких сегментов непригодна. Нужны согласованные schema/examples/checker, в том числе terminal observation на конце бюджета |
| R4, происхождение опыта | Полный manifest: оба source ref/hash, wire/scenario digest, seed/derivation, normalization, профиль dt/лимитов, Python/ОС; observation и raw/requested/applied/stop/advance по каждому шагу, валидный частичный отчёт | Нынешняя структура не доказывает происхождение digital_simulation. Нельзя считать смену execution на measured подтверждением прогона |
| SCOUT-02, реальные фото | ≥20 CHANGED + ≥20 UNCHANGED held-out фотографий, разделённых по сценам, зафиксированные до оценки параметры; recall ≥0.90, FPR ≤0.10, coverage ≥0.90 | Набор не предоставлен. Синтетика и сгенерированные изображения робота не заменяют фото приёмки |
| Приёмка / runtime | Решение по цифровому объёму #1/#2 либо отдельно разрешённому параллельному этапу, совместная фиксация контракта | CI подтверждает проверки, а не разрешает merge/оборудование/PoC |

Ближайшая безопасная программная работа после этого checkpoint — R2/R4 в
существующем draft PR #4, с согласованными schema и отрицательными примерами;
не реализация facade/адаптера. Для продолжения этой документационной работы
оборудование и закупка не нужны. От владельца для лабораторной приёмки нужны
разрешённые реальные фото; порядок съёмки уже описан в [SCOUT-02](../scout-02.md).
