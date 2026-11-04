# INTEGRATION-02C: маршрут и сравнение контроллеров

Продолжение существующего Scout #3 / draft PR #8, без новой задачи или второго
адаптера. Canonical draft.3 и schema SHA-256 не меняются. Внешний worker закреплён
на SkillForge `fa57ef94ce64539f19f8fdd75210a5d25ebb2da8` из PR #12.

## Запуск на Windows

Два отдельных чистых Git checkout. В Scout checkout ветки PR #8. В SkillForge
checkout именно указанной ревизии. Подходит Python 3.12/3.13, stdlib, без GPU.

```powershell
python scripts/check_route_bridge.py --skillforge-root ..\SkillForge --output-dir runs/route-bridge
Start-Process .\runs\route-bridge\index.html
```

Каталог результата должен быть новым/пустым. Ошибки и неудачные попытки сохраняются
до проверки критериев; exit 1 означает непрохождение, а не удаление результата.
Для API-подготовленных immutable snapshots доступны явные source receipts, как
в предыдущем checkpoint. Обычный Git-путь требует чистоты обоих checkout.

## Глобальная миссия

`run_route` использует тот же runner, supervisor и SimRobot, что `run_goal`.
Session содержит A/B/C/HOME. На достижении станции Scout независимо останавливает
робота, подтверждает telemetry, отправляет motion_enabled=false. Worker должен
ответить нулевой canonical command, raw_action=null, limitation=inspection-stop.
Затем прежний SyntheticInspector выполняет fixture inspection. Один zero advance
расходует глобальный тик; следующий сегмент начинается на end+1. HOME завершает
миссию без нового запроса движения. До проверенного stop и ответа перехода нет.

Один процесс/session на всю миссию, без reset clock/seed/epoch/budget на станции.
Это актуальный публичный API worker; историческое предложение пересоздавать
контроллер на каждом сегменте не применяется. GoalSeeker не имеет изменяемого
состояния управления между целями и не использует RNG в act. Scout не копирует
его алгоритм и не вызывает физику SkillForge.

Результат сегмента измеряет [start,end), инспекционный zero tick вне его метрик.
Partial report сохраняет завершённые результаты и подтверждённый trace prefix;
missing/not-started образуют точное покрытие plan. Сбой инспектора тоже вызывает
stop и сохраняет partial, без фиктивного результата станции.

## Зафиксированное сравнение

До запуска выбраны normal, deviations, blocked, sensor-failure, seed 1, dt .05,
бюджет 180 с. По 4 основных запуска на контроллер; каждый повторяется второй раз.
Все 16 попыток сохраняются. Совпадение входов проверяется по полной Scenario,
включая deviations, noise и failure time. Одинаковая политика одного sensor sample
на границу шага исключает влияние лишних stop reads на шум.

Baseline вызывает неизменённый `scout.mission.run_mission` через записывающий
RobotPort. Алгоритм не переписан. Audit хранит полные read/command requested/applied,
stop telemetry, before/after каждого advance. Его отчёт остаётся legacy Scout 1.0;
не выдаётся за canonical GoalSeeker report, поскольку wire фиксирует goal_seeker.
Оба используют одну реализацию физики Scout в независимых запусках.

GoalSeeker reports проходят неизменённый canonical checker. Инспекции хранятся
отдельно с synthetic=true / scenario_fixture. Настоящая камера не запускалась.
Для повторов сравниваются все входы/состояния/события/команды, числа с допуском
1e-9; исключены лишь уникальный epoch и его transport digest. В summary есть также
точные semantic SHA-256 обоих повторов. Другая ОС может дать иной source digest
из-за checkout line endings; среда и оба исходника сохранены для каждого запуска.

Полная миссия считается пройденной только при A/B/C по порядку, корректных
синтетических инспекциях, HOME и подтверждённой остановке. Blocked/fault ожидаются
в двух аварийных сценариях, без guard/contact. Неожиданные ошибки остаются в
знаменателе. Путь — сумма записанных хорд, время — глобальные модельные тики,
включая три inspection ticks. У partial расстояние помечается неполным.

## Численная устойчивость и границы

Полный маршрут выявил cancellation в старой формуле точной дуги при omega≈4e-8:
вычитание близких sin/cos и умножение на v/omega превышало v*dt более чем на 1e-9.
Формула в Scout записана математически эквивалентно через midpoint/sinc, без этого
вычитания. Строгий checker и допуски не ослаблены; есть воспроизводимая регрессия.
Исправление действует для обоих контроллеров только в этой ветке.

Набор мал: вывод о превосходстве контроллера, CV-точности, железе или sim2real не
делается. Продуктовые ручные приёмки остаются открыты. Merge и закупки запрещены
без согласования. [CI access](controller-bridge.md#ci-access-to-the-separate-worker):
нужен read-only SCOUT_SKILLFORGE_READ_TOKEN; без него интеграционные jobs красные,
успешные независимые supervisor tests не считаются Windows runtime acceptance.
