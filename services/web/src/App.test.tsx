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
  expect(html).toContain("Отменить");
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
