# INTEGRATION-02C — checkpoint полного маршрута

Продолжение Scout #3 / draft PR #8. Worker остаётся на SkillForge
`fa57ef94ce64539f19f8fdd75210a5d25ebb2da8`; wire draft.3 не меняется.
[Команды и точные критерии](../integration/route-bridge.md).

Реализован полный маршрут A/B/C/HOME в том же runner; независимый stop и нулевое
подтверждение worker на инспекции; сохранение результатов завершённых сегментов
при сбое следующего. Baseline вызывает прежний Scout mission через записывающий
RobotPort, без копирования контроллера. Синтетические инспекции отделены от CV.

Полный прогон обнаружил потерю точности старой формулы дуги при малом omega.
Исправлена эквивалентной midpoint/sinc формулой, а не ослаблением валидатора.
20 integration tests и 30 исходных core tests прошли на Linux/Python 3.12.14.
Проверены поздний sensor fault, partial после завершённой A, ошибка инспектора,
общий бюджет 3600, непрерывный clock, существующие process faults/guard/stop.
Четыре исходных demo outcome прошли. Измеренные CLI-артефакты добавляются отдельным
последующим коммитом после сверки всего дерева исходников с опубликованным ref.

CI предыдущего head `262367c01192b53405436b0a9f6ba1a77e633e9a`: supervisor tests
прошли на всех 4 Windows/Linux/Python 3.12/3.13 jobs, но jobs завершились failure
из-за отсутствующего read-only SCOUT_SKILLFORGE_READ_TOKEN, до внешнего checkout.
Это не успешный cross-platform runtime. Контрактный CI 41883161429 прошёл;
обычный Scout CI проверяется отдельно. SkillForge fa57ef94 ранее имел 9/9 success.

Никаких изменений main, gh-pages, веток #1/#2/#4 или SkillForge. Приёмки Gate1,
внешний ручной тест, настоящие фото и оборудование остаются открыты. Merge и закупок нет.

## Измеренный результат на зафиксированной паре

Scout `adecc83a0e9818910e1fb2333546adab930f9c66` + worker `fa57ef94ce64539f19f8fdd75210a5d25ebb2da8`. Перед запуском сверены все 79 Scout и 104 SkillForge tracked Git blobs. Полные source digests и среда находятся в каждом отчёте. 8 основных запусков + 8 повторов; все 16 попыток сохранены. Все 8 GoalSeeker reports (с повторами) приняты неизменённым checker draft.3; baseline сохраняет собственный legacy report и полный audit. Все 8 пар совпали также по точному semantic SHA-256 после исключения epoch/его transport digest, помимо проверки чисел в допуске 1e-9.

| Сценарий | Scout baseline: исход / шаги / время / путь | GoalSeeker: исход / шаги / время / путь | Stop / guard |
| --- | --- | --- | --- |
| normal | ROUTE_FINISHED / 981 / 49.05 с / 5.925000 м | GOAL_REACHED / 899 / 44.95 с / 5.909998 м | confirmed / 0 |
| deviations | ROUTE_FINISHED / 981 / 49.05 с / 5.925000 м | GOAL_REACHED / 899 / 44.95 с / 5.909998 м | confirmed / 0 |
| blocked | PATH_BLOCKED / 72 / 3.60 с / 0.540000 м | PATH_BLOCKED / 72 / 3.60 с / 0.540000 м | confirmed / 0 |
| sensor-failure | SENSOR_UNAVAILABLE / 40 / 2.00 с / 0.300000 м | SENSOR_UNAVAILABLE / 40 / 2.00 с / 0.300000 м | confirmed / 0 |

Оба штатных случая: A/B/C по порядку и HOME. В deviations обнаружены две подготовленные синтетические перемены; в normal все три инспекции UNCHANGED. Все заранее выбранные автоматические критерии узкого offline-PoC пройдены. N=4 на контроллер не доказывает превосходство/коммерческую полезность.

[ZIP с HTML и всеми исходными JSON 16 попыток](evidence/route-bridge/paired-route-adecc83a.zip), [summary](evidence/route-bridge/summary.json), [receipt](evidence/route-bridge/RECEIPT.json). Архив: 91 файл, 797982 байта, SHA-256 `74fc8236975014fc0aebae3cd0eb227c216a8a295ddbcaf234aabd87d85982c7`. Проверены CRC, каждый file checksum, все JSON и локальные HTML-ссылки. Архив не содержит исходников SkillForge. Этот последующий evidence/CI commit не меняет runtime проверенного Scout code ref.

## Блокер CI устранён без нового секрета

[SkillForge CI-only draft #13](https://github.com/x3-team/SkillForge/pull/13) запускает закреплённую пару из приватного репозитория с обычным read-only GITHUB_TOKEN: он читает собственный worker и публичный Scout. PAT, новый secret, изменение visibility/прав или публикация приватного кода не нужны. Ветка worker PR #12 не изменена этой работой; новый отдельный CI draft содержит только workflow и checkpoint.

[Run 41884975702](https://github.com/x3-team/SkillForge/actions/runs/41884975702), workflow commit `c2f49656d018ac1227d060426960bd8329ea5e76`: **4/4 success**, Ubuntu/Windows × Python 3.12/3.13. В каждом job фактически прошли 12 worker tests + 30 Scout core tests + 20 integration tests без skip, затем 4 one-goal cases и 16 paired executions. Проверены decoded Windows/Linux job logs, acceptance_passed=true, все repeat checks и наличие четырёх artifacts. [Долговечный CI receipt с job/artifact IDs и метриками](evidence/route-bridge/ci-receipt.json).

После этого реального успешного прогона Scout workflow оставлен независимым supervisor: в нём явно skipped 7 tests, требующих приватный worker, и выполнены 13 независимых tests. Это не называется интеграционным CI. Real-worker приёмка подтверждена полным отдельным прогоном выше. При изменении runtime обязательно обновить pins и повторить общий CI; зелёный независимый supervisor сам по себе этого не заменяет.

Технический результат: узкий цифровой маршрут/инспекция/сравнение автоматически проверены на четырёх средах. Ручная продуктовая приёмка, реальные фото, рынок и оборудование остаются открытыми. Merge и закупок нет.
