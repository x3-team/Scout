# Чекпоинт INTEGRATION-02B: реальная связка одной цели

Дата: 2026-11-04. Продолжение Scout #3 ↔ SkillForge #8 после принятия draft.3
и поручения владельца продолжить отдельный программный этап параллельно с
открытыми приёмками. [Реализация и команды](../integration/controller-bridge.md).

Worker SkillForge: `0df4b22fd8c01f526be3212acea362af2d52f1be` / PR #12.
Перед подключением проверены его API/исходники и неизменённая schema; все104
source blobs внешнего immutable snapshot сверены с Git tree,11 профильных тестов
SkillForge прошли локально. Код GoalSeeker и physics SkillForge в Scout не копируется.

Наблюдаемый результат: четыре реальные пары «публичный worker + SimRobot Scout»,
не форматные примеры и не заранее заданная траектория. Полные report/manifest и
transport logs создаются CLI и проходят canonical checker. Контрольная копия
первых измерений/исходные hashes сохраняются отдельно после проверки нового PR.

## Контрольная копия выполненных запусков

Код Scout: `7b322445dd0f3408409cbfe4a85f14f2b19c4098`.
Проверены все70 source blobs Scout и104 SkillForge по immutable Git tree,
SHA-1 blob и SHA-256; снимки не выдаются за Git history. Полные source digests
обоих продуктов сохранены в [summary](evidence/controller-bridge/summary.json).
[Архив](evidence/controller-bridge/one-goal-7b322445.zip) содержит18 файлов:
открыть index.html после распаковки, исходные canonical JSON и transport рядом.
[Checksum/source receipt](evidence/controller-bridge/RECEIPT.json).

| Случай | Исход | Шаги | Модельное время | Путь | Stop / guard |
| --- | --- | ---: | ---: | ---: | --- |
| forward | GOAL_REACHED |237|11.85 с|1.777500 м|подтверждён /0|
| turn | GOAL_REACHED |193|9.65 с|1.177499 м|подтверждён /0|
| blocked | PATH_BLOCKED |72|3.60 с|0.540000 м|подтверждён /0|
| sensor-failure | SENSOR_UNAVAILABLE |40|2.00 с|0.300000 м|подтверждён /0|

Локально прошли12 bridge unittest (включая реальные четыре случая и отдельные
fault-injection subprocesses),30 исходных core tests и4 demo outcome. Все четыре
измеренных report.json приняты неизменённым canonical checker. Это автоматическая
проверка Linux/Python3.12.14; итог нового Windows/Linux CI фиксируется в PR.
В последующем коммите добавляется только эта контрольная копия и описание;
измерения относятся к указанному code ref, а не к вымышленному новому прогону.

| Случай | Критерий |
| --- | --- |
| forward | GOAL_REACHED, подтверждённый stop, canonical report |
| turn | GOAL_REACHED, исходная omega и normalization сохранены, одна физика Scout |
| blocked | PATH_BLOCKED, ни одного advance после safety-stop |
| sensor-failure | SENSOR_UNAVAILABLE, подтверждённый stop без последующего движения |
| Сбой процесса | Timeout, EOF/exit0/exit7, partial line и исключение не становятся успехом |
| Неверный ответ | Version/epoch/TTL/NaN/bool/overspeed/oversized/duplicate JSON не доходят до SimRobot.command |
| Ошибка телеметрии / stop | Не записываются NaN/вымышленные позиции; неподтверждённый stop остаётся fault |

Локально Linux/CPython3.12.14: профильные тесты и четыре первых запуска прошли;
CI Windows/Linux нового head проверяется отдельно. Ожидаются четыре bridge jobs
и исходные проверки Scout. Фактические финальные counts/CI сохраняются в PR,
а не подставляются из предыдущего контрактного этапа.

Объём намеренно одна цель. Это не закрывает изначальные восемь сравнительных
запусков, A/B/C/HOME, инспекции, SCOUT-02 по настоящим фото или продуктовый Gate1.
Следующий checkpoint — расширение того же runner на миссию и baseline comparison,
без второго движка и без изменения принятого wire.

Изменения изолированы в новой ветке, stacked draft на PR #4. Ветки #1/#2/#4,
main/gh-pages и SkillForge не изменяются; issue #3 остаётся открытой. Merge,
закупки, реальное оборудование, камеры, сетевой сервис и расходы не запускались.
