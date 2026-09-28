import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { ModelDemoPage } from "./ModelDemoPage";
import type { ModelDemoState } from "./modelDemo";

test("страница различает время источника и расчёта и показывает четыре горизонта", () => {
  const initialState: ModelDemoState = {
    scenarios: [{ id: "held-out-01", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [{ id: "s1", name: "Температура", sensorType: "heat", picket: "ПК 1+00", value: "61 °C", state: "warning" }] }],
    index: 0, requestToken: 0,
    calculation: { calculationId: "calc-1", scenario: { id: "held-out-01", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [] }, prediction: { calculatedAt: "2026-09-29T10:00:00Z", pNow: .1, p6h: .2, p12h: .3, p24h: .4, decisions: { now: false, "6h": false }, factors: [] } }
  };
  const html = renderToStaticMarkup(<ModelDemoPage navigate={() => undefined} onRefresh={async () => undefined} role="district_dispatcher" initialState={initialState} />);

  expect(html).toContain("Время показаний");
  expect(html).toContain("Рассчитано");
  expect(html).toContain("Сейчас");
  expect(html).toContain("6 часов");
  expect(html).toContain("12 часов");
  expect(html).toContain("24 часа");
  expect(html).toContain("Порог предупреждения не превышен");
  expect(html).not.toMatch(/catboost|\.cbm|fastapi/i);
});

test("исполнитель после публикации не получает нерабочую ссылку в закрытый раздел", () => {
  const scenario = { id: "held-out-05", sourceTimestamp: "2026-09-01T10:00:00Z", objectId: "42", objectName: "Объект 42", district: "САО", dangerousSection: "ПК 1+00", sensors: [] };
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
