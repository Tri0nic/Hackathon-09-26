import type { ModelDemoCalculation, ModelDemoScenario } from "./types";

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

export function modelFactorLabel(feature: string): string {
  if (feature.includes("alarm")) return "Срабатывания тревоги";
  if (feature.includes("temperature") || feature.includes("heat")) return "Температура и тепловые датчики";
  if (feature.includes("smoke")) return "Датчики дыма";
  if (feature.includes("gas")) return "Газовые датчики";
  if (feature.includes("event")) return "События оборудования";
  if (feature.includes("malfunction")) return "Неисправности оборудования";
  if (feature.includes("stale")) return "Актуальность показаний";
  return "Состояние оборудования";
}
