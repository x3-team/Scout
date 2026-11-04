# INTEGRATION-02B: публичный процесс и одна цель

По следующему поручению владельца продолжается разрешённый параллельный
offline-этап. Canonical wire принят на Scout
`0aa463e9e3c570e7a56e24f0255a0d910cf433a5`; schema SHA-256
`88640878bb3dc2358cd197a6277a497d98e266ec8d7bd4054b1e6429778f1788`.
Публичный worker получен из [SkillForge PR #12](https://github.com/x3-team/SkillForge/pull/12),
точный ref `0df4b22fd8c01f526be3212acea362af2d52f1be`,
[его API](https://github.com/x3-team/SkillForge/blob/0df4b22fd8c01f526be3212acea362af2d52f1be/docs/integration/SCOUT-WORKER.md).

## Проверяемая цель этого этапа

Настоящий GoalSeeker в отдельном процессе отдаёт JSON-команды; двигает модель
только существующий SimRobot Scout. Четыре случая: достижение одной цели прямо,
достижение цели после поворота, остановка перед препятствием и потеря датчика.
Каждый результат проходит неизменённый canonical checker draft.3.

Это маленький runtime-checkpoint, а не полный PoC маршрута A/B/C/HOME,
синтетической инспекции и сравнения двух контроллеров. Эти исходные критерии
сохраняются для следующего этапа; они не объявляются пройденными здесь.

## Реализация и границы

- ProcessController вызывает публичный `python -m skillforge.scout_worker`
  через argv/stdin/stdout, без shell и импорта внутренних моделей SkillForge.
- Startup ограничен отдельно 10 с; каждый ответ — 1 с. Блокировка чтения,
  записи и даже незаконченная строка находятся под внешним deadline. При отказе
  процесс завершается, поздний ответ не попадает в следующий step/epoch.
- JSON UTF-8 без BOM/LF, ≤64 KiB и depth≤32; запрет duplicate keys/nonfinite,
  неправильных version/epoch/step/target/TTL/скоростей и silent clamp ответа.
  Контрактная schema закреплена по digest и не менялась в этом этапе.
- Independent local stop выполняется до терминального запроса и в finally.
  Успешный exit/EOF/нулевая команда не подтверждают stop: нужна телеметрия.
- DigitalProbeRobot сохраняет исходную физику Scout и кеширует шумовой sample
  на границе времени. Повторное чтение stop telemetry не потребляет новый RNG.
- Одноцелевой runner сохраняет полные canonical report/manifest, отдельный
  process transcript и исходный Scenario. При исключении сохраняется только
  подтверждённый prefix; неподтверждённое in-flight observation/response остаётся
  в transport sidecar. Motion-enabled исходный запрос не переписывается в
  вымышленную остановленную запись ради заполнения partial report.
- Полный source hash обоих продуктов вычисляется по tracked bytes чистого Git
  checkout либо проверенному immutable snapshot receipt. Запуск на грязном
  checkout не называется measured. Результаты пишутся только в runs/ или вне
  дерева исходников; исходники контроллера в Scout не копируются.

Single-goal report содержит план только первой станции. Для поворота первая
цель нормального сценария перенесена в (0.6,1.8); это сохранённый вариант входа,
не незаметная правка исходного сценария. Полный Scenario в sidecar может содержать
остальные станции, но они в этом этапе не обходятся и не инспектируются.

## Повторение Windows / PowerShell

Нужны Python3.12+ и Git, два отдельных checkout указанных точных ревизий.
SkillForge работает из соседнего каталога, без pip/install и без сетевого доступа
во время расчёта. Из чистого Scout checkout:

```powershell
$env:SKILLFORGE_ROOT = (Resolve-Path ..\SkillForge).Path
python -m unittest discover -s integration_tests -v
python scripts/check_goal_bridge.py --skillforge-root ..\SkillForge --output-dir runs/goal-bridge
Start-Process .\runs\goal-bridge\index.html
```

Реальный worker pin жёстко проверяется, moving branch не подставляется.
В API-подготовленных snapshots можно передать --scout-source-pin и
--skillforge-source-pin с проверенными commit/полным списком SHA-256/Git blob SHA.
Обычному Git checkout эти аргументы не нужны. В CI используется отдельный
pinned checkout SkillForge; автоматический Windows не выдаётся за ручной запуск.

Результат: summary.json, index.html и каталоги forward/turn/blocked/sensor-failure
с report.json, transport.json, scenario.json и runtime.json. Seed=1; epoch новой
попытки уникален и не зависит от RNG. Поэтому полные JSON не обязаны совпадать
побайтово при повторе; сравниваются физические метрики/траектория/исход в допуске
1e-9 в одной среде. Межплатформенная побитовая идентичность не заявляется.

## Приёмка и остаток

Проверяются GoalReached в допуске0.025 м, raw/normalized turn, нулевая
подтверждённая остановка blocked/sensor-fault, count advance, timeout/EOF/ошибки
и достоверный partial prefix. Тестовые workers лежат только в integration_tests;
измеренный check_goal_bridge всегда запускает публичный SkillForge worker.

Следующий шаг после ревью этого checkpoint — полный маршрут/инспекция и
сравнение с прежним Scout baseline на четырёх фиксированных сценах. Камера,
ручная приёмка продуктов, внешние испытания и оборудование остаются отдельными.
Python stop, supervisor и модель мгновенного торможения не являются аппаратным
watchdog. Процесс изолирует выполнение контроллера, но не является sandbox для
произвольного недоверенного кода. Публичный worker — проверенный код двух проектов.
