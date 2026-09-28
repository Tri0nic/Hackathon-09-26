import { demoData } from "./demo";
import { alertKindLabel, createPublicRequestId, smsRecipientsForAlert, smsRoleLabel } from "./domain";
import type { Alert, AppData, Channel, CreateRequestInput, Decision, Employee, ExecutorGroup, ExecutorRequestAction, MaintenanceRequest, ModelMetrics, RequestComment, RequestKind, RequestPriority, RequestStatus, RiskLevel, RiskObject, SmsDeliveryStatus, SmsNotification, SmsProcessingStatus } from "./types";

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
const recipients = (value: RiskLevel) => value === "black" ? ["Техник", "Группа немедленного реагирования"] : value === "red" ? ["Техник"] : [];
const deliveryStatuses: SmsDeliveryStatus[] = ["delivered", "failed"];
const processingStatuses: SmsProcessingStatus[] = ["undelivered", "new", "in_progress", "completed", "cancelled"];
const executorGroups: ExecutorGroup[] = ["technician", "response_team"];
const requestPriorities: RequestPriority[] = ["normal", "high", "emergency"];
const requestKinds: RequestKind[] = ["inspection", "repair", "emergency"];

export function normalizeApiData(payload: RawApiPayload): AppData {
  const alertRows = payload.alerts.map((row): Alert => {
    const alertLevel = level(row.level);
    return {
      id: text(row.id), episodeId: text(row.episodeId), objectId: text(row.objectId), objectName: text(row.objectName, "Объект не указан"),
      kind: "fire", level: alertLevel, horizon: text(row.horizon, "24h"), probability: numeric(row.probability),
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
    id: text(row.id), publicId: text(row.publicId, text(row.id).replace(/\D/g, "").slice(-5).padStart(5, "0")), alertId: text(row.alertId), objectId: text(row.objectId), objectName: text(row.objectName, objects.find((item) => item.id === row.objectId)?.name ?? "Объект не указан"),
    picket: text(row.picket) || undefined, recommendation: text(row.recommendation, "Провести проверку объекта."),
    requestKind: requestKinds.includes(row.requestKind as RequestKind) ? row.requestKind as RequestKind : "inspection",
    executorGroup: executorGroups.includes(row.executorGroup as ExecutorGroup) ? row.executorGroup as ExecutorGroup : "technician",
    priority: requestPriorities.includes(row.priority as RequestPriority) ? row.priority as RequestPriority : "normal",
    description: text(row.description, text(row.recommendation, "Провести проверку объекта.")),
    dueAt: text(row.dueAt) || undefined, comment: text(row.comment) || undefined,
    creatorRole: text(row.creatorRole, "district_dispatcher"), assigneeId: text(row.assigneeId) || undefined, assigneeName: text(row.assigneeName) || undefined,
    comments: list<RequestComment>(row.comments),
    status: (["under_review", "scheduled"].includes(text(row.status)) ? "in_progress" : text(row.status, "new")) as RequestStatus,
    createdAt: text(row.createdAt, new Date(0).toISOString()), updatedAt: text(row.updatedAt, new Date(0).toISOString())
  }));
  const sms = payload.sms.map((row): SmsNotification => {
    const relatedAlert = alertRows.find((alert) => alert.episodeId === row.episodeId);
    const translatedRole = smsRoleLabel(text(row.role, text(row.recipientId, "Получатель не указан")));
    const deliveryStatus = deliveryStatuses.includes(row.status as SmsDeliveryStatus) ? row.status as SmsDeliveryStatus : "delivered";
    const processingStatus = deliveryStatus === "failed"
      ? "undelivered"
      : processingStatuses.includes(row.processingStatus as SmsProcessingStatus) && row.processingStatus !== "undelivered" ? row.processingStatus as SmsProcessingStatus : "in_progress";
    return {
      id: text(row.id), episodeId: text(row.episodeId), alertLevel: level(row.alertLevel),
      episodeTitle: text(row.episodeTitle, relatedAlert ? `${alertKindLabel(relatedAlert.kind)} · ${relatedAlert.objectName}` : "Эпизод без названия"),
      recipientId: text(row.recipientId), role: translatedRole,
      recipientName: text(row.recipientName, translatedRole), sentAt: text(row.sentAt, new Date(0).toISOString()),
      content: text(row.content), incidentSummary: text(row.incidentSummary, relatedAlert?.factors[0]?.label ?? relatedAlert?.recommendation ?? "Причина не указана"),
      assigneeName: text(row.assigneeName) || undefined,
      status: deliveryStatus,
      processingStatus, requestId: text(row.requestId) || undefined
    };
  });
  const rawMetrics = payload.metrics;
  const metrics: ModelMetrics = {
    modelVersion: text(rawMetrics.modelVersion, text(rawMetrics.version, "не указана")),
    labelSource: text(rawMetrics.labelSource, "Proxy-разметка MVP (не подтверждённые пожары)"),
    rocAuc: numeric(rawMetrics.rocAuc), precision: numeric(rawMetrics.precision), recall: numeric(rawMetrics.recall), alertsPerDay: numeric(rawMetrics.alertsPerDay)
  };
  return { demo: false, objects, alerts: alertRows, requests, sms, metrics };
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

  async createRequest(input: CreateRequestInput): Promise<MaintenanceRequest> {
    const alert = memory.alerts.find((item) => item.id === input.alertId);
    if (!alert) throw new Error("Предупреждение не найдено");
    const response = import.meta.env.VITE_DEMO_MODE === "false"
      ? await json<{ id: string; publicId: string }>(`/api/alerts/${input.alertId}/requests`, { method: "POST", body: JSON.stringify({ ...input, recommendation: alert.recommendation }) })
      : { id: `REQ-${Date.now()}`, publicId: createPublicRequestId(memory.requests.map((request) => request.publicId)) };
    const now = new Date().toISOString();
    const value: MaintenanceRequest = {
      id: response.id, publicId: response.publicId, alertId: input.alertId, objectId: alert.objectId, objectName: alert.objectName,
      picket: alert.channels[0]?.picketRaw ?? undefined, recommendation: alert.recommendation,
      requestKind: input.requestKind, executorGroup: input.executorGroup, priority: input.priority,
      description: input.description, dueAt: input.dueAt, comment: input.comment, creatorRole: input.creatorRole,
      comments: [], status: "new", createdAt: now, updatedAt: now
    };
    memory.requests.unshift(value);
    if (import.meta.env.VITE_DEMO_MODE !== "false") {
      const district = memory.objects.find((item) => item.id === alert.objectId)?.district ?? "Не указан";
      smsRecipientsForAlert(alert.level, district).forEach((employee, index) => {
        memory.sms.unshift({
          id: `SMS-${Date.now()}-${index}`, requestId: value.id, episodeId: alert.episodeId,
          episodeTitle: `${alertKindLabel(alert.kind)} · ${alert.objectName}`, alertLevel: alert.level,
          recipientId: employee.id, role: smsRoleLabel(input.executorGroup), recipientName: employee.name,
          sentAt: now, content: `Создана заявка: ${input.description}`,
          incidentSummary: alert.factors[0]?.label ?? input.description, status: "delivered", processingStatus: "new"
        });
      });
    }
    return value;
  },

  async claimRequest(id: string, employee: Employee): Promise<void> {
    const request = memory.requests.find((item) => item.id === id);
    if (import.meta.env.VITE_DEMO_MODE === "false") {
      await json(`/api/requests/${id}/claim`, { method: "POST", body: JSON.stringify({ employeeId: employee.id, employeeName: employee.name, executorGroup: employee.group }) });
    } else {
      if (!request || request.assigneeId || request.executorGroup !== employee.group) throw new Error("Заявка уже взята или недоступна");
    }
    if (request) {
      request.assigneeId = employee.id;
      request.assigneeName = employee.name;
      request.status = "in_progress";
      request.updatedAt = new Date().toISOString();
      memory.sms.filter((sms) => sms.requestId === id && sms.status === "delivered").forEach((sms) => { sms.assigneeName = employee.name; sms.processingStatus = "in_progress"; });
    }
  },

  async executeRequestAction(id: string, employee: Employee, action: ExecutorRequestAction, comment: string): Promise<void> {
    const request = memory.requests.find((item) => item.id === id);
    if (import.meta.env.VITE_DEMO_MODE === "false") {
      await json(`/api/requests/${id}/executor-action`, { method: "POST", body: JSON.stringify({ employeeId: employee.id, employeeName: employee.name, action, comment }) });
      return;
    }
    if (!request || request.assigneeId !== employee.id || request.status !== "in_progress") throw new Error("Недостаточно прав для изменения заявки");
    if (action === "cancel" && !comment.trim()) throw new Error("Укажите причину отмены");
    if (comment.trim()) request.comments.push({ id: `COMMENT-${Date.now()}`, employeeId: employee.id, employeeName: employee.name, text: comment.trim(), createdAt: new Date().toISOString() });
    if (action === "release") { request.assigneeId = undefined; request.assigneeName = undefined; request.status = "new"; }
    if (action === "complete") request.status = "completed";
    if (action === "cancel") request.status = "rejected";
    request.updatedAt = new Date().toISOString();
    memory.sms.filter((sms) => sms.requestId === id && sms.status === "delivered").forEach((sms) => {
      sms.processingStatus = action === "release" ? "new" : action === "complete" ? "completed" : action === "cancel" ? "cancelled" : "in_progress";
      if (action === "release") sms.assigneeName = undefined;
    });
  },

  async updateRequest(id: string, status: RequestStatus): Promise<void> {
    if (import.meta.env.VITE_DEMO_MODE === "false") await json(`/api/requests/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
    const request = memory.requests.find((item) => item.id === id);
    if (request) { request.status = status; request.updatedAt = new Date().toISOString(); }
  }
};
