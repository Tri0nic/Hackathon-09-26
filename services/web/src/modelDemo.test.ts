import { expect, test } from "vitest";
import { canPublishModelDemo, initialModelDemoState, modelDemoInputSummary, modelDemoPublicationPath, modelDemoReducer, modelDemoScenarioLabel, modelFactorInfluence, modelFactorLabel, uniqueModelFactors } from "./modelDemo";
import type { ModelDemoState } from "./modelDemo";
import type { ModelDemoCalculation, ModelDemoScenario } from "./types";

const scenario = (id: string): ModelDemoScenario => ({
  id, sourceTimestamp: "2026-09-01T10:00:00Z", objectId: `object-${id}`, objectName: `Объект ${id}`,
  district: "САО", dangerousSection: "ПК 1+00–1+20", sensors: [{ id: "s1", name: "Температура", sensorType: "heat", picket: "ПК 1+00", value: "61 °C", state: "warning" }],
  inputs: [{ label: "Тревоги за 5 минут", value: "3" }]
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

test("после передачи диспетчер открывает созданное предупреждение", () => {
  expect(modelDemoPublicationPath("district_dispatcher", "alert-42")).toBe("/alerts/alert-42");
  expect(modelDemoPublicationPath("ods_dispatcher", "alert-42")).toBe("/alerts/alert-42");
  expect(modelDemoPublicationPath("technician", "alert-42")).toBeUndefined();
});

test("технические признаки получают понятные подписи", () => {
  expect(modelFactorLabel("alarm_count_5m")).toBe("Тревоги за 5 минут");
  expect(modelFactorLabel("max_temperature_24h")).toBe("Максимальная температура за 24 часа");
  expect(modelFactorLabel("gas_channel_count")).toBe("Газовые датчики");
  expect(modelFactorLabel("event_count_30m")).toBe("События за 30 минут");
});

test("влияние фактора показано короткой отдельной меткой", () => {
  expect(modelFactorInfluence(.42)).toBe("Повышает риск");
  expect(modelFactorInfluence(-.42)).toBe("Снижает риск");
  expect(modelFactorInfluence(0)).toBe("Не влияет");
});

test("повтор одного признака на разных горизонтах показывается один раз", () => {
  const factors = uniqueModelFactors([
    { horizon: "6h", feature: "alarm_count_5m", value: 2, contribution: .2 },
    { horizon: "24h", feature: "alarm_count_5m", value: 2, contribution: .7 },
    { horizon: "24h", feature: "smoke_heat_5m", value: 1, contribution: .5 }
  ]);

  expect(factors).toHaveLength(2);
  expect(factors[0]).toMatchObject({ feature: "alarm_count_5m", contribution: .7 });
});

test("разные технические признаки с одной подписью не дублируют строку", () => {
  const factors = uniqueModelFactors([
    { horizon: "24h", feature: "active_state_duration", value: 2, contribution: .4 },
    { horizon: "24h", feature: "object_state_code", value: 1, contribution: -.8 }
  ]);

  expect(factors).toHaveLength(1);
  expect(factors[0]).toMatchObject({ feature: "object_state_code", contribution: -.8 });
});

test("сценарий получает короткое название по текущим показателям", () => {
  expect(modelDemoScenarioLabel([{ label: "Дым или нагрев", value: "Есть" }])).toBe("Дым или нагрев");
  expect(modelDemoScenarioLabel([{ label: "Неисправности за 5 минут", value: "2" }])).toBe("Неисправность оборудования");
  expect(modelDemoScenarioLabel([{ label: "События за 30 минут", value: "91" }])).toBe("События оборудования");
  expect(modelDemoScenarioLabel([{ label: "Тревоги за 5 минут", value: "0" }])).toBe("Штатная работа");
});

test("шесть технических признаков сворачиваются в три понятных пояснения", () => {
  expect(modelDemoInputSummary([
    { label: "События за 30 минут", value: "91" },
    { label: "Тревоги за 5 минут", value: "0" },
    { label: "Неисправности за 5 минут", value: "0" },
    { label: "Дым или нагрев", value: "Нет" },
    { label: "Газовые тревоги за 5 минут", value: "0" },
    { label: "Неактуальные каналы", value: "119" },
  ])).toEqual([
    { title: "Поступление данных", value: "91 событие за последние 30 минут" },
    { title: "Тревожные признаки", value: "Не обнаружены за последние 5 минут" },
    { title: "Качество данных", value: "119 каналов без актуальных показаний" },
  ]);
});
