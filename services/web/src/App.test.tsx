import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { App } from "./App";
import { demoData } from "./demo";

test("полная карточка предупреждения сохраняет ключевые блоки", () => {
  const html = renderToStaticMarkup(
    <App initialData={demoData} initialPath={`/alerts/${demoData.alerts[0].id}`} />
  );

  expect(html).toContain("Динамика вероятности");
  expect(html).toContain("Возраст и ТО");
  expect(html).toContain("Решение диспетчера");
  expect(html).toContain("Статусы SMS");
  expect(html).toContain("Демонстрационный контекст");
});

test("карточка использует цвет фактического уровня риска", () => {
  const data = structuredClone(demoData);
  data.alerts[0].level = "black";

  const html = renderToStaticMarkup(
    <App initialData={data} initialPath={`/alerts/${data.alerts[0].id}`} />
  );

  expect(html).toContain("risk-score level-black");
});

test("шапка позволяет выбрать одну из четырёх пользовательских ролей", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/" />);

  expect(html).toContain('aria-label="Текущая роль"');
  expect(html).toContain("Техник");
  expect(html).toContain("Диспетчер района");
  expect(html).toContain("Диспетчер ОДС");
  expect(html).toContain("Группа реагирования");
});

test("верхняя шапка не показывает демонстрационную плашку", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/" />);

  expect(html).not.toContain(">DEMO<");
});

test("таблица каналов не показывает источник метаданных", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/objects/demo-object-1" />);

  expect(html).toContain("Значения и возраст оборудования");
  expect(html).not.toContain("источник метаданных");
  expect(html).not.toContain("<th>Источник</th>");
  expect(html).not.toContain("Demo-оценка");
  expect(html).not.toContain("По первому событию");
});

test("журнал SMS показывает объект и тип события и ведёт на отдельное сообщение", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/sms" />);

  expect(html).not.toContain("Ролевая рассылка, статусы доставки и дедупликация");
  expect(html).not.toContain("Повторы одного уровня и эпизода");
  expect(html).toContain("Объект и тип");
  expect(html).toContain("Уровень происшествия");
  expect(html).toContain("Причина");
  expect(html).toContain("Ответственный");
  expect(html).toContain("Доставка");
  expect(html).toContain("Обработка");
  expect(html).toContain("<th>Получатель</th>");
  expect(html).not.toContain("Роль / получатель");
  expect(html).toContain("Коллектор №1 · участок Северный");
  expect(html).toContain("Пожарный риск");
  expect(html).toContain('href="/sms/SMS-2201"');
});

test("журнал SMS отображает понятные эпизоды, русских получателей и разные статусы", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/sms" />);

  expect(html).toContain("Коллектор №1 · участок Северный");
  expect(html).toContain("Илья Сергеевич Иванов");
  expect(html).toContain("Взято в работу");
  expect(html).toContain("Риск в течение 6 часов");
});

test("недоставленное SMS синхронизирует доставку и обработку", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/sms" />);

  expect(html).not.toContain("В очереди");
  expect(html).not.toContain("Ошибка");
  expect(html).not.toContain("Ожидает обработки");
  expect(html.match(/Недоставлено/g)).toHaveLength(2);
});

test("отдельный экран SMS выглядит как письмо и содержит данные происшествия", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/sms/SMS-2201" />);

  expect(html).toContain("Назад в журнал SMS");
  expect(html).toContain("От:");
  expect(html).toContain("Кому:");
  expect(html).toContain("Тема:");
  expect(html).toContain("Система мониторинга рисков АО «Москоллектор»");
  expect(html).toContain("Коллектор №1 · участок Северный");
  expect(html).toContain("ПК 12.50–12.90");
  expect(html).toContain("Температура ПК 12+50");
  expect(html).toContain("68 °C");
  expect(html).toContain("Проверить участок ПК 12+50–12+90");
});

test("ОДС видит аналитику, а техник — только рабочие разделы и выбор сотрудника", () => {
  const ods = renderToStaticMarkup(<App initialData={demoData} initialPath="/" initialRole="ods_dispatcher" />);
  const technician = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests" initialRole="technician" />);

  expect(ods).toContain("Аналитика");
  expect(technician).not.toContain("Аналитика");
  expect(technician).not.toContain("Предупреждения");
  expect(technician).not.toContain("Журнал SMS");
  expect(technician).toContain('aria-label="Текущий сотрудник"');
  expect(technician).toContain("Доступные заявки");
  expect(technician).toContain("Мои заявки");
});

test("исполнитель не может открыть журнал SMS по прямой ссылке", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/sms" initialRole="response_team" />);

  expect(html).toContain("Рабочее место ГБР");
  expect(html).not.toContain("Журнал SMS");
});

test("у своей заявки исполнитель видит управление, комментарий и подтверждаемое взятие", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests" initialRole="technician" />);

  expect(html).toContain('aria-haspopup="dialog"');
  expect(html).toContain("Добавить комментарий");
  expect(html).toContain("Снять с себя");
  expect(html).toContain("Выполнено");
  expect(html).toContain("Отклонить");
});

test("районный диспетчер открывает полную форму заявки", () => {
  const alert = demoData.alerts[0];
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath={`/alerts/${alert.id}/request`} initialRole="district_dispatcher" />);

  expect(html).toContain("Создание заявки");
  expect(html).toContain("Группа исполнителей");
  expect(html).toContain("Описание неисправности");
  expect(html).toContain("Срок выполнения");
});

test("форма ОДС фиксирует экстренный приоритет и ГБР", () => {
  const alert = demoData.alerts[3];
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath={`/alerts/${alert.id}/request`} initialRole="ods_dispatcher" />);

  expect(html).toContain("Экстренная заявка ОДС");
  expect(html).toContain("Группа быстрого реагирования");
  expect(html).toContain("Экстренный");
  expect(html).not.toContain("Обычный</option>");
});

test("системный футер с моделью удалён", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/" initialRole="ods_dispatcher" />);

  expect(html).not.toContain("Система работает");
  expect(html).not.toContain("Модель: catboost");
});

test("прямая ссылка на запрещённый раздел возвращает исполнителя к заявкам", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/analytics" initialRole="technician" />);

  expect(html).toContain("Рабочее место техника");
  expect(html).not.toContain("ROC AUC");
});

test("исполнитель видит занятые коллегами заявки и ответственного", () => {
  const data = structuredClone(demoData);
  data.requests[1].assigneeId = "tech-petrova";
  data.requests[1].assigneeName = "Мария Андреевна Петрова";
  const html = renderToStaticMarkup(<App initialData={data} initialPath="/requests" initialRole="technician" />);

  expect(html).toContain("Занятые заявки группы");
  expect(html).toContain("Мария Андреевна Петрова");
});

test("верхний профиль не показывает служебную подпись и открывает страницу сотрудника", () => {
  const header = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests" initialRole="technician" />);
  const profile = renderToStaticMarkup(<App initialData={demoData} initialPath="/profile" initialRole="technician" />);

  expect(header).toContain('href="/profile"');
  expect(header).not.toContain("Закреплённые объекты");
  expect(profile).toContain("Профиль сотрудника");
  expect(profile).toContain("Илья Сергеевич Иванов");
  expect(profile).toContain("САО");
  expect(profile).toContain("Коллектор №1 · участок Северный");
});

test("журнал предупреждений не обещает технические сбои и не содержит решения", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/alerts" initialRole="ods_dispatcher" />);

  expect(html).not.toContain("Пожарные риски и технические сбои — раздельно");
  expect(html).not.toContain("<th>Решение</th>");
  expect(html).not.toContain("Технический сбой");
});

test("заявка показывает пятизначный номер, исходный комментарий и кто её взял", () => {
  const data = structuredClone(demoData);
  data.requests[0].comment = "Проверить доступ в помещение до выезда";
  const html = renderToStaticMarkup(<App initialData={data} initialPath="/requests" initialRole="ods_dispatcher" />);

  expect(html).toContain("Кто взял задачу");
  expect(html).toContain("Комментарий к заявке");
  expect(html).toContain("Проверить доступ в помещение до выезда");
  expect(html).toMatch(/>\d{5}</);
});

test("в заявках доступны только четыре согласованных статуса", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests" initialRole="ods_dispatcher" />);

  expect(html).toContain("Новая");
  expect(html).toContain("В работе");
  expect(html).toContain("Выполнена");
  expect(html).toContain("Отклонена");
  expect(html).not.toContain("На рассмотрении");
  expect(html).not.toContain("Запланирована");
});

test("оба диспетчера создают заявку из списка, районный видит только свой район", () => {
  const district = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests" initialRole="district_dispatcher" />);
  const chief = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests" initialRole="ods_dispatcher" />);

  expect(district).toContain('href="/requests/new"');
  expect(district).toContain("Коллектор №1 · участок Северный");
  expect(district).not.toContain("Коллектор №9 · участок Южный");
  expect(chief).toContain('href="/requests/new"');
  expect(chief).toContain("Коллектор №9 · участок Южный");
});

test("форма из списка предлагает диспетчеру доступные объекты", () => {
  const district = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests/new" initialRole="district_dispatcher" />);
  const chief = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests/new" initialRole="ods_dispatcher" />);

  expect(district).toContain("Объект и предупреждение");
  expect(district).toContain("Коллектор №1 · участок Северный");
  expect(district).not.toContain("Коллектор №9 · участок Южный");
  expect(chief).toContain("Коллектор №9 · участок Южный");
});

test("районный диспетчер не создаёт заявку по прямой ссылке на чужой район", () => {
  const foreignAlert = demoData.alerts.find((alert) => alert.objectId === "demo-object-4")!;
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath={`/alerts/${foreignAlert.id}/request`} initialRole="district_dispatcher" />);

  expect(html).toContain("Предупреждение не найдено");
  expect(html).not.toContain("Коллектор №9 · участок Южный");
});

test("карточка предупреждения подписывает технический ID эпизода", () => {
  const alert = demoData.alerts[0];
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath={`/alerts/${alert.id}`} initialRole="ods_dispatcher" />);

  expect(html).toContain(`Технический ID эпизода: ${alert.episodeId}`);
});

test("журнал SMS не повторяет ответственного в строках одного инцидента", () => {
  const data = structuredClone(demoData);
  data.sms[1].assigneeName = data.sms[0].assigneeName;
  data.sms[1].requestId = "ANOTHER-REQUEST-SAME-INCIDENT";
  const html = renderToStaticMarkup(<App initialData={data} initialPath="/sms" initialRole="ods_dispatcher" />);

  expect(html.match(/Илья Сергеевич Иванов/g)).toHaveLength(2);
});

test("BLACK в демонстрационном журнале уведомляет техника и всех сотрудников ГБР района", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/sms" initialRole="ods_dispatcher" />);

  expect(html).toContain("Алексей Дмитриевич Соколов");
  expect(html).toContain("Наталья Викторовна Орлова");
  expect(html).toContain("Сергей Павлович Волков");
});

test("панель диспетчера предлагает четыре горизонта и все уровни тревоги", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/" initialRole="district_dispatcher" />);

  expect(html).toContain('aria-label="Горизонт прогноза"');
  expect(html).toContain('value="now"');
  expect(html).toContain('value="6h"');
  expect(html).toContain('value="12h"');
  expect(html).toContain('value="24h"');
  expect(html).toContain('aria-label="Уровень тревоги"');
  expect(html).toContain("Чёрный");
  expect(html).toContain("Красный");
  expect(html).toContain("Жёлтый");
  expect(html).toContain("Зелёный");
});

test("фильтр района доступен ОДС и скрыт у районного диспетчера", () => {
  const district = renderToStaticMarkup(<App initialData={demoData} initialPath="/" initialRole="district_dispatcher" />);
  const ods = renderToStaticMarkup(<App initialData={demoData} initialPath="/" initialRole="ods_dispatcher" />);

  expect(district).not.toContain('aria-label="Район"');
  expect(ods).toContain('aria-label="Район"');
  expect(ods).toContain("Все районы");
  expect(ods).toContain("САО");
  expect(ods).toContain("ЮАО");
});

test("таблица заявок показывает уровень тревоги связанного предупреждения", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests" initialRole="ods_dispatcher" />);

  expect(html).toContain("Уровень тревоги");
  expect(html).toContain("Чёрный · Событие сейчас");
});

test("карточка предупреждения скрывает служебные адресаты, модель и mock-плашку", () => {
  const alert = demoData.alerts[0];
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath={`/alerts/${alert.id}`} initialRole="district_dispatcher" />);

  expect(html).not.toContain("<dt>Адресаты</dt>");
  expect(html).not.toContain("<dt>Модель</dt>");
  expect(html).not.toContain(alert.modelVersion);
  expect(html).not.toContain("Mock-источник");
  expect(html).toContain(alert.context);
});

test("ФИО в заявках ведут в карточку сотрудника", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/requests" initialRole="ods_dispatcher" />);

  expect(html).toContain('href="/profile/tech-ivanov"');
  expect(html).toContain("Илья Сергеевич Иванов");
});

test("получатели и ответственные в SMS ведут в карточки сотрудников", () => {
  const journal = renderToStaticMarkup(<App initialData={demoData} initialPath="/sms" initialRole="ods_dispatcher" />);
  const message = renderToStaticMarkup(<App initialData={demoData} initialPath="/sms/SMS-2201" initialRole="ods_dispatcher" />);

  expect(journal).toContain('href="/profile/tech-ivanov"');
  expect(journal).toContain('href="/profile/response-orlova"');
  expect(message).toContain('href="/profile/tech-ivanov"');
});

test("карточка сотрудника показывает ФИО, роль, районы и объекты", () => {
  const technician = renderToStaticMarkup(<App initialData={demoData} initialPath="/profile/tech-ivanov" initialRole="ods_dispatcher" />);
  const response = renderToStaticMarkup(<App initialData={demoData} initialPath="/profile/response-orlova" initialRole="ods_dispatcher" />);

  expect(technician).toContain("Илья Сергеевич Иванов");
  expect(technician).toContain("Техник");
  expect(technician).toContain("САО");
  expect(technician).toContain("Коллектор №1 · участок Северный");
  expect(response).toContain("Наталья Викторовна Орлова");
  expect(response).toContain("Группа быстрого реагирования");
  expect(response).toContain("ЮАО");
});

test("неизвестный идентификатор сотрудника не подменяется совпавшим ФИО", () => {
  const data = structuredClone(demoData);
  data.requests[1].assigneeId = "retired-employee";
  data.requests[1].assigneeName = "Илья Сергеевич Иванов";
  data.requests[1].comments = [];
  const html = renderToStaticMarkup(<App initialData={data} initialPath="/requests" initialRole="ods_dispatcher" />);

  expect(html).toContain("Илья Сергеевич Иванов");
  expect(html).not.toContain('href="/profile/tech-ivanov"');
});

test("ответственный в SMS связывается с профилем по заявке, а не по ФИО", () => {
  const data = structuredClone(demoData);
  data.sms[0].assigneeName = "Отображаемое имя ответственного";
  const html = renderToStaticMarkup(<App initialData={data} initialPath="/sms" initialRole="ods_dispatcher" />);

  expect(html).toContain('<a href="/profile/tech-ivanov" class="person-link">Отображаемое имя ответственного</a>');
});

test("исполнитель не открывает профиль сотрудника вне доступных объектов", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/profile/response-orlova" initialRole="technician" />);

  expect(html).toContain("Сотрудник не найден");
  expect(html).not.toContain("Наталья Викторовна Орлова");
});
