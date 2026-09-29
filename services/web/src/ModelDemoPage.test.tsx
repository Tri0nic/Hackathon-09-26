import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { ModelDemoPage } from "./ModelDemoPage";
import type { ModelDemoState } from "./modelDemo";

test("страница различает время источника и расчёта и показывает четыре горизонта", () => {
  const initialState: ModelDemoState = {
    scenarios: [{ id: "held-out-01", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [{ id: "s1", name: "Температура", sensorType: "heat", picket: "ПК 1+00", value: "61 °C", state: "warning" }], inputs: [{ label: "Тревоги за 5 минут", value: "0" }] }],
    index: 0, requestToken: 0,
    calculation: { calculationId: "calc-1", scenario: { id: "held-out-01", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [], inputs: [{ label: "Тревоги за 5 минут", value: "0" }] }, prediction: { calculatedAt: "2026-09-29T10:00:00Z", pNow: .1, p6h: .2, p12h: .3, p24h: .4, decisions: { now: false, "6h": false }, factors: [] } }
  };
  const html = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={initialState} />);

  expect(html).toContain("Время показаний");
  expect(html).toContain("Рассчитано");
  expect(html).toContain("Сейчас");
  expect(html).toContain("6 часов");
  expect(html).toContain("12 часов");
  expect(html).toContain("24 часа");
  expect(html).toContain("Проверка обученной модели");
  expect(html).toContain("Входные данные");
  expect(html).toContain("Штатный пример");
  expect(html).toContain("Порог предупреждения не превышен");
  expect(html).not.toContain("Факторы прогноза");
  expect(html).not.toContain('class="demo-badge"');
  expect(html).not.toContain("Показания взяты из тестовой выборки");
  expect(html).not.toMatch(/catboost|\.cbm|fastapi/i);
});

test("до расчёта результат пуст и тип примера не раскрывается", () => {
  const scenario = { id: "held-out-01", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [], inputs: [{ label: "Дым или нагрев", value: "Есть" }] };
  const html = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={{ scenarios: [scenario], index: 0, requestToken: 0 }} />);

  expect(html).toContain("Проверка обученной модели");
  expect(html).toContain("Дым или нагрев");
  expect(html).toContain("Нажмите «Рассчитать прогноз»");
  expect(html).not.toContain("Тревожный пример");
  expect(html).not.toContain("Штатный пример");
});

test("после расчёта превышение порога помечается как тревожный пример", () => {
  const scenario = { id: "held-out-05", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [], inputs: [{ label: "Тревоги за 5 минут", value: "3" }] };
  const initialState: ModelDemoState = {
    scenarios: [scenario], index: 0, requestToken: 0,
    calculation: { calculationId: "calc-1", scenario, prediction: { calculatedAt: "2026-09-29T10:00:00Z", pNow: .1, p6h: .7, p12h: .8, p24h: .9, decisions: { "6h": true }, factors: [{ horizon: "6h", feature: "alarm_count_5m", value: 3, contribution: .5 }] } }
  };
  const html = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={initialState} />);

  expect(html).toContain("Тревожный пример");
  expect(html).not.toContain("Факторы прогноза");
  expect(html).toMatch(/<button class="primary">Передать диспетчеру<\/button>/);
  expect(html).not.toContain("+0.500");
});

test("сводный блок поступления и качества данных не показывается", () => {
  const scenario = { id: "held-out-01", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [], inputs: [{ label: "События за 30 минут", value: "91" }, { label: "Тревоги за 5 минут", value: "0" }, { label: "Неисправности за 5 минут", value: "0" }, { label: "Дым или нагрев", value: "Нет" }, { label: "Газовые тревоги за 5 минут", value: "0" }, { label: "Неактуальные каналы", value: "119" }] };
  const html = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={{ scenarios: [scenario], index: 0, requestToken: 0 }} />);

  expect(html).not.toContain("Поступление данных");
  expect(html).not.toContain("Тревожные признаки");
  expect(html).not.toContain("Качество данных");
  expect(html).not.toContain('class="model-demo-inputs"');
});

test("датчик показывает только значение, а длинное служебное имя заменяет короткой подписью", () => {
  const scenario = { id: "held-out-01", sourceTimestamp: "2026-01-01T00:00:00Z", objectId: "111", objectName: "ДП объект Бета", district: "ЦАО", dangerousSection: "Не определён", sensors: [{ id: "47838", name: "Анд.Н.Д1-3 гал.0ПК2–6т.с,Д12-14 ПК11–гал.0ПК5каб. Гагар.Д4-6 ПК95–78т.с,Д7-11 ПК73-96каб.", sensorType: "Газовый датчик", value: "Норма", state: "warning", lastSeenAt: "2025-12-12T05:49:41Z" }], inputs: [] };
  const html = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={{ scenarios: [scenario], index: 0, requestToken: 0 }} />);

  expect(html).toContain("Газовый датчик · канал 47838");
  expect(html).toContain('class="sensor-state warning text-value">Норма</span>');
  expect(html).not.toContain("Требует внимания");
  expect(html).not.toContain("Анд.Н.Д1-3");
});

test("датчик показывает время и текстовый статус, а объект — закреплённых сотрудников", () => {
  const scenario = { id: "held-out-01", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [{ id: "smoke-1", name: "Датчик дыма", sensorType: "smoke", picket: "ПК 1+00", value: "Тревога", state: "danger", lastSeenAt: "2026-09-01T09:55:00Z" }], assignedEmployees: [{ id: "tech-ivanov", name: "Илья Сергеевич Иванов", role: "Техник" }], inputs: [] };
  const html = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={{ scenarios: [scenario], index: 0, requestToken: 0 }} />);

  expect(html).toContain("Закреплённые сотрудники");
  expect(html).toContain("Илья Сергеевич Иванов");
  expect(html).toContain("Техник");
  expect(html).toContain("Последнее измерение");
  expect(html).toContain("Тревога");
  expect(html).toContain("model-demo-sensor danger");
});

test("исполнитель после публикации не получает нерабочую ссылку в закрытый раздел", () => {
  const scenario = { id: "held-out-05", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [], inputs: [] };
  const initialState: ModelDemoState = {
    scenarios: [scenario], index: 0, requestToken: 0, alertId: "alert-1",
    calculation: { calculationId: "calc-1", scenario, prediction: { calculatedAt: "2026-09-29T10:00:00Z", pNow: .1, p6h: .7, p12h: .8, p24h: .9, decisions: { "6h": true }, factors: [] } }
  };

  const executor = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="technician" initialState={initialState} />);
  const dispatcher = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={initialState} />);

  expect(executor).toContain("Передано диспетчеру");
  expect(executor).not.toContain("Открыть предупреждение");
  expect(dispatcher).toContain("Открыть предупреждение");
});

test("текстовые состояния датчика помечаются для показа целым словом", () => {
  const scenario = { id: "held-out-01", sourceTimestamp: "2026-01-01T00:00:00Z", objectId: "111", objectName: "Объект", district: "ВАО", dangerousSection: "ПК258+8", sensors: [{ id: "disabled-1", name: "Н1 ПК186", sensorType: "Состояние устройства", picket: "ПК186", value: "Обесточен", state: "danger", lastSeenAt: "2025-12-21T00:45:00Z" }, { id: "broken-1", name: "В13 ПК281", sensorType: "Состояние устройства", picket: "ПК281", value: "Неисправен", state: "danger", lastSeenAt: "2025-12-21T00:45:00Z" }], inputs: [] };
  const html = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={{ scenarios: [scenario], index: 0, requestToken: 0 }} />);

  expect(html.match(/class="sensor-state danger text-value"/g)).toHaveLength(2);
});
