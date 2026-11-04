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
