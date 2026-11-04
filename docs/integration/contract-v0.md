# Canonical-проект scout-skillforge/0.1-draft.3

Статус: **реализован формат и его офлайн-проверка; совместная приёмка и runtime
не выполнены**. Источник схемы — Scout. Это следующая ревизия после draft.2,
а не отчёт текущего mission runner Scout 1.0 или SkillForge schema_version=1.
Старые сообщения не мигрируют молча: неизвестная/прежняя версия отвергается.
Предложение SkillForge принято как требования на ref
`0fc2e8d96c6669782945e42bc78357d0aa4609ed`; нужен явный repin и ответ по этой
canonical-ревизии, а не одобрение старой draft.2.

[JSON Schema](contract-v0.schema.json), [форматные примеры](contract-v0.examples.json),
[чекпоинт и исходный отчёт проверки](../reviews/contract-draft3.md).
Исторический [draft.2](https://github.com/x3-team/Scout/blob/547a343a462169461be3a5e33ea6766f83b5b988/docs/integration/contract-v0.md)
остаётся доступным по точному ref; его диагностические пробелы превращены в
positive/negative acceptance cases новой ревизии.

## Назначение и границы

Только `digital_known_map`: CPU, идеальная поза/статическая карта, синтетический
body-clearance. Движение рассчитывает только Scout; SkillForge предоставляет
GoalSeeker через будущий facade. Scout владеет миссией, инспекцией, фильтром
безопасности, часами и остановкой. Камера/инспекционные результаты контроллеру
не передаются. Этот профиль не предназначен для реального робота.

Полный формат задаёт `session`, `observation`, `command`, `result` и
`experiment_report`. Каждое wire-сообщение ≤64 KiB UTF-8. Агрегированный отчёт
может содержать до 3601 записей и ограничен 16 MiB; глубина JSON ≤32.
JSON strict: повтор ключа, NaN/Infinity, bool вместо числа, неизвестные поля,
неправильная версия и неограниченные массивы запрещены.

## Единицы и профиль

`lab`: X вправо, Y вверх; `base`: X вперёд, Y влево. yaw от +X против часовой
стрелки, [-π,π). Единицы SI: м, с, рад, м/с, рад/с. Прямоугольники —
x_min/y_min/x_max/y_max; порядок и полный свободный круг робота проверяются.
`profile`: dt=0.05, max_steps=3600, v≤0.15, |omega|≤0.8, stopping clearance=0.22,
range=1.0, arrival tolerance=0.025, supervisor controller timeout=1.0 с.
Радиус=0.14 м; другой профиль/привод требует новой ревизии.

Front body clearance — консервативный допустимый прямой ход центра до контакта
корпуса с расширенными AABB/границами, не сырой луч и не минимальная евклидова
дистанция. Значение 1 м насыщено. `unavailable` требует null. Потеря дальномера,
невалидная локализация/возраст или clearance≤0.22 запрещают advance, включая
поворот на месте. Один observation потребляет один результат сенсора/RNG.

Схема ограничивает числовую структуру, а checker — связи и переходы. Нет
дублирования физики, проверки всего непрерывного swept path или доказательства
реальной остановки: это остаётся обязанностью Scout и отдельной приёмки.

## Попытка, сообщения и активное состояние

`trial_id` — метка опыта; `epoch` — уникальный ID живой попытки, независимый от
seed. Все сообщения, manifest и results содержат одинаковые trial/epoch.
Worker restart завершает попытку и создаёт новый epoch; продолжение старого
движения запрещено. Эти ID не являются аутентификацией.

Валидатор получает **доверенные active_trial_id/active_epoch от вызывающей
стороны**, а не извлекает активность из проверяемого сообщения. Поэтому replay
целого старого отчёта с внутренне согласованными ID тоже отвергается. Уникальность
epoch между реальными процессами должен обеспечить будущий runner; офлайн-fixture
не может подтвердить такую уникальность в мире.

Session неизменяемо закрепляет профиль, seed, world, start pose, plan, контроллер и
synthetic provenance. Неизменяемый `plan` содержит 1..4 уникальных segment_id и
target_id (A/B/C/HOME), координаты целей, порядок. Для полного PoC отдельно
фиксируется маршрут A/B/C/HOME; короткие планы нужны для контрактных проверок.

Observation содержит trial/epoch/segment/target, global step/time, pose, velocity,
motion_enabled, sensor status/body-clearance/sample time. Координаты цели берутся
из plan; цель не меняется внутри сегмента. Невалидная исходная телеметрия не
попадает в метрики: отсутствие принятого observation записывается как partial
report, а не заполняется вымышленной позой.
Facade получает plan вместе с session и может найти координаты цели по
segment_id/target_id без чтения агрегированного отчёта или импортов ядра Scout.

Command повторяет ID и step наблюдения, TTL=`step+1`; v/omega — requested.
Задний ход и превышение wire-лимитов отвергаются. `mode=stop` эквивалентен строго
нулевым компонентам. Внутренний finite raw Action может превышать профиль:
facade обязан записать raw, применить clamp v∈[0,0.15], omega∈[-0.8,0.8] и вернуть
корректный requested. Это фиксирует `si-lab-yaw-clamp-v1`; неверный wire-ответ
не исправляется задним числом. Текст отклонённого ответа хранится отдельно,
ограниченно, в rejected_response; NaN никогда не становится числом журнала.

## Глобальные часы и сегменты — R2

Единственный clock: `time_s=step*dt_s`, абсолютный допуск 1e-9 с. Step начинается
с 0 и увеличивается ровно одним подтверждённым advance. Возраст сенсора —
[-1e-9, 2*dt+1e-9]; нарушения дают STALE_SENSOR и не разрешают движение.

Команды возможны на 0..3599. После advance3599 разрешены terminal observation
3600/time180, локальная остановка и отчёт. На step3600 нет нового controller
command/advance. Прежний дефект maximum179.95 устранён: законное
3599*0.05=179.95000000000002 принимается. Структурный максимум времени оставляет
допуск; смысловой clock по-прежнему проверяется независимо.

Result содержит trial/epoch/segment/target, start_step/end_step, outcome,
stop_confirmed, metrics. Интервал физических advance — **[start,end)**;
завершающее observation имеет индекс end. steps=end-start, duration=steps*dt.
Например start280/end300 — 20 шагов/1 с; global end time=15 с.
Distance — сумма хорд принятых pose на том же интервале, не выдуманная оценка:
она сверяется с trace и v*dt. Guard activations считаются по тому же сегменту,
включая терминальную попытку шага, которую guard отверг целиком.

Inspection-stop на end сохраняет zero requested/applied, raw_action=null,
motion_enabled=false; GoalSeeker не вызывается. Остановка подтверждена отдельной
телеметрией. Этот нулевой advance расходует общий бюджет, но находится уже вне
метрик завершённого navigation-сегмента. Следующий сегмент начинается на end+1.
Первый пример: A — advance0/1, result end2; inspection2 — zero advance;
B начинается на3 и fault сразу, без advance. Ни clock, ни budget не сбрасываются.

## Журнал и независимая остановка

Каждая запись trace содержит observation, phase, raw_action, requested,
rejected_response, applied, limitation, advance, guard/controller fault и
local_stop. Navigate выполняет один advance. Inspection делает один нулевой
advance. Terminal/interrupted — последняя запись, без advance, applied=null.
После terminal ни одной новой записи движения нет.

**local_stop и controller command — разные действия.** На terminal requested=null
не означает «не вызывать robot.stop()». Local stop всегда attempted=true;
confirmed=true требует отдельную проверенную нулевую velocity telemetry.
Observation перед остановкой может честно содержать прежнюю ненулевую скорость.
Её нельзя подменять нулями ради красивого результата.

Footprint guard — отдельный терминальный случай: сохраняются finite raw и
корректный requested предпринятого шага, applied=null/advance=false, local stop.
Такой запрос допускается только при исходно безопасном observation и step<3600.
При более раннем sensor/path stop контроллер не вызывается и requested=null.

## Закрытая таблица исходов — SCOUT-C1

| status | Разрешённый reason |
| --- | --- |
| completed | GOAL_REACHED |
| blocked | PATH_BLOCKED |
| timeout | MISSION_TIMEOUT |
| fault | STOP_NOT_CONFIRMED, FOOTPRINT_GUARD, INVALID_OBSERVATION, LOCALIZATION_UNAVAILABLE, SENSOR_UNAVAILABLE, STALE_SENSOR, CONTROLLER_TIMEOUT, CONTROLLER_EXCEPTION, INVALID_COMMAND, RUNNER_EXCEPTION |

Проверяется соответствие **в обе стороны** и контекст события. Исправный sensor
не доказывает GOAL_REACHED: нужна записанная pose в arrival tolerance и
подтверждённая остановка. Завершение одного сегмента не означает всей миссии.
MISSION_TIMEOUT требует исчерпания глобального бюджета и не скрывает fault.

Приоритеты: неподтверждённая остановка → guard → невалидное исходное наблюдение →
локализация → потеря дальномера → stale/future → fault контроллера → fault runner →
PATH_BLOCKED → MISSION_TIMEOUT → GOAL_REACHED. В одном controller_fault ровно один
из CONTROLLER_TIMEOUT/CONTROLLER_EXCEPTION/INVALID_COMMAND. RUNNER_EXCEPTION и
INVALID_OBSERVATION допускают partial без выдуманного завершающего observation.
confirmed=true несовместим с reason STOP_NOT_CONFIRMED; confirmed=false всегда
даёт этот fault независимо от остальных причин, которые сохраняются в error/trace.

Supervisor wall-clock timeout1с будущего facade требует отдельного процесса и
отклонения позднего ответа по epoch/step; этот checker не запускает callback и
не реализует watchdog. Модельная мгновенная остановка не равна отключению моторов.

## Полный manifest и честный partial report — R4

Каждый report содержит manifest с обязательной структурой:

| Поле | Смысл / проверка |
| --- | --- |
| trial_id/epoch | Совпадают с session, report, trace и result |
| wire_revision/wire_schema_sha256 | Точная версия и SHA-256 сырых LF UTF-8 байтов canonical schema |
| sources.scout / sources.skillforge | Commit40hex и source_sha256 обоих продуктов; обязательны для digital_simulation |
| scene / scene_sha256 | Разрешённая полная сцена: world, start_pose, plan, sensor noise/failure; hash canonical JSON, связь с session/plan |
| seed.value / derivation | uint64; identity-u64-v1, без скрытого reseed на сегменте |
| profile / normalization | Полный фиксированный профиль и si-lab-yaw-clamp-v1, сверка с session |
| environment | Python и ОС; обязательны для digital_simulation |

Canonical JSON для scene: json.dumps(sort_keys=True, separators=(',', ':'),
ensure_ascii=False, allow_nan=False), UTF-8, SHA-256. Source digest: тот же
canonical JSON списка [{path,sha256}], отсортированного по UTF-8 path, для всех
tracked-файлов чистого checkout указанного commit; sha256 — hash сырых байтов
файла. Будущий runner обязан записывать проверенный чистый source snapshot.
Checker проверяет формат source digest, но не скачивает репозиторий и не
аутентифицирует происхождение: это не доказательство выполненного опыта.

contract_example разрешает null source digests/environment, сохраняя все ключи.
Все опубликованные literal fixtures имеют именно этот execution. Переименование
такого примера в digital_simulation отвергается. В памяти тестируется и полная
структура measured profile с фиктивными metadata; это не результат PoC и не
сохраняется как измеренный отчёт.

report_complete описывает полноту записи, а не успешность обхода. Полный отчёт
может закончиться blocked/fault/timeout, но содержит terminal и фактический
result последнего начатого сегмента; error=null. Results, missing_results и
not_started_segments образуют непересекающееся покрытие plan. Не начатые цели
не превращаются в выполненные. Ошибки входят в знаменатель оценки попыток N.

При ошибке runner/наблюдения/сохранения: report_complete=false, error(code,
at_step,message), точный last_confirmed_step, фактический trace prefix,
missing_results для начатых без результата и not_started для остальных.
Если завершающее observation не получено, его не придумывать. Если остановку
нельзя подтвердить, stop.telemetry=null/confirmed=false и STOP_NOT_CONFIRMED.
Ошибка записи на недоступный диск не гарантирует сохранения самого partial:
нужен отдельный резервный путь будущего runner; здесь проверяется формат.

## Повторение и передача SkillForge

```powershell
python scripts/check_integration_contract.py --examples-dir runs/contract-fixtures
python scripts/check_contract_clock.py --output runs/contract-clock-check.json
```

Проверка стандартной библиотекой использует только собственное подмножество JSON
Schema, с отказом на неизвестный keyword. Это офлайн-проверка проектных fixtures,
а не универсальный JSON Schema runtime. Для воспроизведения нужен полный checkout
данного ref или **вся зависимость checker**: check_integration_contract.py,
contract_schema.py, contract_fixtures.py, contract_checks.py и check_contract_clock.py
из scripts плюс schema/examples из docs/integration. SHA-256 closure перечислены
в отчёте; копировать только старые три pinned файла недостаточно.

Следующий шаг: SkillForge явно закрепляет ref/digest этой версии, повторяет её
проверки и фиксирует согласие или воспроизводимые замечания. Runtime-адаптер,
ручная приёмка продуктов, аппаратная безопасность и merge остаются отдельными
решениями. Никаких закупок эта ревизия не разрешает.
