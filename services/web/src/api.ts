import { demoData } from "./demo";
import type { Alert, AppData, Channel, Decision, MaintenanceRequest, ModelMetrics, RequestStatus, RiskLevel, RiskObject, SmsNotification } from "./types";

const baseUrl = import.meta.env.VITE_API_URL ?? "";
let memory = structuredClone(demoData);

interface RawApiPayload {
  objects: Record<string, unknown>[];
  alerts: Record<string, unknown>[];
  requests: Record<string, unknown>[];
  sms: Record<string, unknown>[];
  metrics: Record<string, unknown>;
}

const levels: RiskLevel[] = ["black", "red", "yellow", "green"];
const text = (value: unknown, fallback = "") => typeof value === "string" ? value : fallback;
const numeric = (value: unknown, fallback = 0) => typeof value === "number" && Number.isFinite(value) ? value : fallback;
const level = (value: unknown): RiskLevel => levels.includes(value as RiskLevel) ? value as RiskLevel : "green";
const list = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const recipients = (value: RiskLevel) => value === "black" ? ["Техник", "Диспетчер района", "Диспетчер ОДС", "Группа реагирования"] : value === "red" ? ["Техник", "Диспетчер района", "Диспетчер ОДС"] : value === "yellow" ? ["Диспетчер района", "Диспетчер ОДС"] : ["Диспетчер ОДС"];

export function normalizeApiData(payload: RawApiPayload): AppData {
  const alertRows = payload.alerts.map((row): Alert => {
    const alertLevel = level(row.level);
    return {
      id: text(row.id), episodeId: text(row.episodeId), objectId: text(row.objectId), objectName: text(row.objectName, "Объект не указан"),
      kind: row.kind === "malfunction" ? "malfunction" : "fire", level: alertLevel, horizon: text(row.horizon, "24h"), probability: numeric(row.probability),
      pNow: numeric(row.pNow), p6h: numeric(row.p6h), p12h: numeric(row.p12h), p24h: numeric(row.p24h, numeric(row.probability)),
      calculatedAt: text(row.calculatedAt, new Date(0).toISOString()), modelVersion: text(row.modelVersion, "не указана"), stale: row.stale === true, current: row.current !== false,
      picketFrom: typeof row.picketFrom === "number" ? row.picketFrom : undefined, picketTo: typeof row.picketTo === "number" ? row.picketTo : undefined,
      channels: list<Channel>(row.channels), factors: list<Alert["factors"][number]>(row.factors), recommendation: text(row.recommendation, "Провести проверку объекта."),
      context: text(row.context, "Данные не предоставлены."), recipients: list<string>(row.recipients).length ? list<string>(row.recipients) : recipients(alertLevel),
      history: list<Alert["history"][number]>(row.history), decisions: list<Decision>(row.decisions)
    };
  });
  const objects = payload.objects.map((row): RiskObject => {
    const related = alertRows.find((alert) => alert.objectId === row.id);
    return { id: text(row.id), name: text(row.name, "Объект без названия"), district: text(row.district, "Не указан"), channelCount: numeric(row.channelCount), level: related?.level ?? level(row.level), probability: related?.probability ?? numeric(row.probability), channels: list<Channel>(row.channels) };
  });
  const requests = payload.requests.map((row): MaintenanceRequest => ({
    id: text(row.id), alertId: text(row.alertId), objectId: text(row.objectId), objectName: text(row.objectName, objects.find((item) => item.id === row.objectId)?.name ?? "Объект не указан"),
    picket: text(row.picket) || undefined, recommendation: text(row.recommendation, "Провести проверку объекта."), status: text(row.status, "new") as RequestStatus,
    createdAt: text(row.createdAt, new Date(0).toISOString()), updatedAt: text(row.updatedAt, new Date(0).toISOString())
  }));
  const rawMetrics = payload.metrics;
  const metrics: ModelMetrics = {
    modelVersion: text(rawMetrics.modelVersion, text(rawMetrics.version, "не указана")),
    labelSource: text(rawMetrics.labelSource, "Proxy-разметка MVP (не подтверждённые пожары)"),
    rocAuc: numeric(rawMetrics.rocAuc), precision: numeric(rawMetrics.precision), recall: numeric(rawMetrics.recall), alertsPerDay: numeric(rawMetrics.alertsPerDay)
  };
  return { demo: false, objects, alerts: alertRows, requests, sms: payload.sms as unknown as SmsNotification[], metrics };
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.status === 204 ? (undefined as T) : response.json();
}

export const api = {
  async load(): Promise<AppData> {
    if (import.meta.env.VITE_DEMO_MODE !== "false") return structuredClone(memory);
    try {
      const [objects, alerts, requests, sms, metrics] = await Promise.all([
        json<Record<string, unknown>[]>("/api/objects"), json<Record<string, unknown>[]>("/api/alerts"),
        json<Record<string, unknown>[]>("/api/requests"), json<Record<string, unknown>[]>("/api/sms"), json<Record<string, unknown>>("/api/model/metrics")
      ]);
      memory = normalizeApiData({ objects, alerts, requests, sms, metrics });
      return structuredClone(memory);
    } catch {
      return structuredClone(memory);
    }
  },

  async addDecision(alertId: string, decision: string, comment: string): Promise<Decision> {
    const value = { decision, comment, decidedAt: new Date().toISOString() };
    if (import.meta.env.VITE_DEMO_MODE !== "false") {
      memory.alerts.find((alert) => alert.id === alertId)?.decisions.unshift(value);
      return value;
    }
    await json(`/api/alerts/${alertId}/decision`, { method: "POST", body: JSON.stringify({ decision, comment }) });
    return value;
  },

  async createRequest(alertId: string, recommendation: string): Promise<MaintenanceRequest> {
    const alert = memory.alerts.find((item) => item.id === alertId)!;
    if (import.meta.env.VITE_DEMO_MODE === "false") await json(`/api/alerts/${alertId}/requests`, { method: "POST", body: JSON.stringify({ recommendation }) });
    const value: MaintenanceRequest = { id: `REQ-${1043 + memory.requests.length}`, alertId, objectId: alert.objectId, objectName: alert.objectName, picket: alert.channels[0]?.picketRaw ?? undefined, recommendation, status: "new", createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
    memory.requests.unshift(value);
    return value;
  },

  async updateRequest(id: string, status: RequestStatus): Promise<void> {
    if (import.meta.env.VITE_DEMO_MODE === "false") await json(`/api/requests/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
    const request = memory.requests.find((item) => item.id === id);
    if (request) { request.status = status; request.updatedAt = new Date().toISOString(); }
  }
};
