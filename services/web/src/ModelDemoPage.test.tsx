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
  expect(html).toContain("Тревоги за 5 минут");
  expect(html).toContain("Повышает риск");
  expect(html).not.toContain("+0.500");
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
