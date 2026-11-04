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
