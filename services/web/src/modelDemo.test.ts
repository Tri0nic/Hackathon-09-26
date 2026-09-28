import { expect, test } from "vitest";
import { canPublishModelDemo, initialModelDemoState, modelDemoReducer, modelFactorLabel } from "./modelDemo";
import type { ModelDemoState } from "./modelDemo";
import type { ModelDemoCalculation, ModelDemoScenario } from "./types";

const scenario = (id: string): ModelDemoScenario => ({
  id, sourceTimestamp: "2026-09-01T10:00:00Z", objectId: `object-${id}`, objectName: `Объект ${id}`,
  district: "САО", dangerousSection: "ПК 1+00–1+20", sensors: [{ id: "s1", name: "Температура", sensorType: "heat", picket: "ПК 1+00", value: "61 °C", state: "warning" }]
});

test("следующие показания циклически перебирают 24 записи и очищают прогноз", () => {
  const scenarios = Array.from({ length: 24 }, (_, index) => scenario(String(index + 1)));
  let state: ModelDemoState = { ...initialModelDemoState, scenarios, index: 23, calculation: { calculationId: "calc", scenario: scenarios[23], prediction: { calculatedAt: "2026-09-01T10:01:00Z", pNow: .1, p6h: .2, p12h: .3, p24h: .4, decisions: {}, factors: [] } } as ModelDemoCalculation };

  state = modelDemoReducer(state, { type: "next" });

  expect(state.index).toBe(0);
  expect(state.calculation).toBeUndefined();
});

test("запоздалый ответ не подменяет уже переключённые показания", () => {
  const scenarios = [scenario("1"), scenario("2")];
  let state = modelDemoReducer({ ...initialModelDemoState, scenarios }, { type: "predict-start", token: 1 });
  state = modelDemoReducer(state, { type: "next" });
  state = modelDemoReducer(state, { type: "predict-success", token: 1, calculation: { calculationId: "old", scenario: scenarios[0], prediction: { calculatedAt: "2026-09-01T10:01:00Z", pNow: .1, p6h: .2, p12h: .3, p24h: .4, decisions: { "6h": true }, factors: [] } } });

  expect(state.index).toBe(1);
  expect(state.calculation).toBeUndefined();
});

test("публикация доступна только при превышении порога", () => {
  expect(canPublishModelDemo({ now: false, "6h": false })).toBe(false);
  expect(canPublishModelDemo({ now: false, "6h": true })).toBe(true);
});

test("технические признаки получают понятные подписи", () => {
  expect(modelFactorLabel("alarm_count_5m")).toContain("Срабатывания");
  expect(modelFactorLabel("max_temperature_24h")).toContain("Температура");
  expect(modelFactorLabel("gas_channel_count")).toContain("Газ");
  expect(modelFactorLabel("event_count_30m")).toContain("События");
});
