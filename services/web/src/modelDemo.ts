import type { ModelDemoCalculation, ModelDemoFactor, ModelDemoInput, ModelDemoScenario } from "./types";

export interface ModelDemoState {
  scenarios: ModelDemoScenario[];
  index: number;
  calculation?: ModelDemoCalculation;
  alertId?: string;
  busy?: "loading" | "predicting" | "publishing" | "clearing";
  error?: string;
  requestToken: number;
}

export const initialModelDemoState: ModelDemoState = { scenarios: [], index: 0, busy: "loading", requestToken: 0 };

export type ModelDemoAction =
  | { type: "load-success"; scenarios: ModelDemoScenario[] }
  | { type: "failure"; message: string }
  | { type: "next" }
  | { type: "predict-start"; token: number }
  | { type: "predict-success"; token: number; calculation: ModelDemoCalculation }
  | { type: "publish-start" }
  | { type: "publish-success"; alertId: string }
  | { type: "clear-start" }
  | { type: "clear-success" };

export function modelDemoReducer(state: ModelDemoState, action: ModelDemoAction): ModelDemoState {
  if (action.type === "load-success") return { ...state, scenarios: action.scenarios, index: 0, busy: undefined, error: undefined };
  if (action.type === "failure") return { ...state, busy: undefined, error: action.message };
  if (action.type === "next") return { ...state, index: state.scenarios.length ? (state.index + 1) % state.scenarios.length : 0, calculation: undefined, alertId: undefined, error: undefined, busy: undefined, requestToken: state.requestToken + 1 };
  if (action.type === "predict-start") return { ...state, calculation: undefined, alertId: undefined, error: undefined, busy: "predicting", requestToken: action.token };
  if (action.type === "predict-success") return action.token === state.requestToken ? { ...state, calculation: action.calculation, busy: undefined } : state;
  if (action.type === "publish-start") return { ...state, busy: "publishing", error: undefined };
  if (action.type === "publish-success") return { ...state, busy: undefined, alertId: action.alertId };
  if (action.type === "clear-start") return { ...state, busy: "clearing", error: undefined };
  return { ...state, busy: undefined, calculation: undefined, alertId: undefined, error: undefined, requestToken: state.requestToken + 1 };
}

export const canPublishModelDemo = (decisions: Record<string, boolean>): boolean => Object.values(decisions).some(Boolean);

const windowLabel = (feature: string): string => {
  const match = feature.match(/_(5m|30m|1h|6h|12h|24h)$/);
  if (!match) return "";
  return ({ "5m": "за 5 минут", "30m": "за 30 минут", "1h": "за час", "6h": "за 6 часов", "12h": "за 12 часов", "24h": "за 24 часа" } as Record<string, string>)[match[1]];
};

export function modelFactorLabel(feature: string): string {
  const window = windowLabel(feature);
  if (feature.startsWith("alarm_count")) return `Тревоги ${window}`.trim();
  if (feature.startsWith("malfunction_count")) return `Неисправности ${window}`.trim();
  if (feature.startsWith("event_count")) return `События ${window}`.trim();
  if (feature.startsWith("max_temperature")) return `Максимальная температура ${window}`.trim();
  if (feature.includes("smoke_heat")) return `Дым или нагрев ${window}`.trim();
  if (feature.includes("smoke")) return "Датчики дыма";
  if (feature.includes("heat") || feature.includes("temperature")) return "Температурные датчики";
  if (feature.includes("gas_alarm")) return `Газовые тревоги ${window}`.trim();
  if (feature.includes("gas")) return "Газовые датчики";
  if (feature.includes("event")) return "События оборудования";
  if (feature.includes("malfunction")) return "Неисправности оборудования";
  if (feature.includes("stale")) return "Неактуальные показания";
  return "Состояние оборудования";
}

export const modelFactorInfluence = (contribution: number): string => contribution > 0 ? "Повышает риск" : contribution < 0 ? "Снижает риск" : "Не влияет";

export function uniqueModelFactors(factors: ModelDemoFactor[]): ModelDemoFactor[] {
  const unique = new Map<string, ModelDemoFactor>();
  for (const factor of factors) {
    const current = unique.get(factor.feature);
    if (!current || Math.abs(factor.contribution) > Math.abs(current.contribution)) unique.set(factor.feature, factor);
  }
  return [...unique.values()].sort((left, right) => Math.abs(right.contribution) - Math.abs(left.contribution));
}

export function modelDemoScenarioLabel(inputs: ModelDemoInput[]): string {
  const values = new Map(inputs.map((input) => [input.label, input.value]));
  const positive = (label: string) => Number(values.get(label) ?? 0) > 0;
  if (values.get("Дым или нагрев") === "Есть") return "Дым или нагрев";
  if (positive("Газовые тревоги за 5 минут")) return "Газовая тревога";
  if (positive("Неисправности за 5 минут")) return "Неисправность оборудования";
  if (positive("Тревоги за 5 минут")) return "Срабатывания тревоги";
  return "Штатная работа";
}
