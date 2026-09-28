import type { AlertKind, Channel, Employee, ExecutorGroup, RequestPriority, RiskLevel, SmsDeliveryStatus, SmsProcessingStatus, UserRole } from "./types";

export const employees: Employee[] = [
  { id: "tech-ivanov", name: "Илья Сергеевич Иванов", group: "technician" },
  { id: "tech-petrova", name: "Мария Андреевна Петрова", group: "technician" },
  { id: "tech-sokolov", name: "Алексей Дмитриевич Соколов", group: "technician" },
  { id: "response-orlova", name: "Наталья Викторовна Орлова", group: "response_team" },
  { id: "response-volkov", name: "Сергей Павлович Волков", group: "response_team" }
];

export function allowedNavigation(role: UserRole): string[] {
  if (role === "ods_dispatcher") return ["/", "/objects", "/alerts", "/requests", "/analytics", "/sms"];
  if (role === "district_dispatcher") return ["/", "/objects", "/alerts", "/requests", "/sms"];
  return ["/requests", "/objects"];
}

export function canCreateRequest(role: UserRole, executor: ExecutorGroup, priority: RequestPriority): boolean {
  return role === "district_dispatcher" || (role === "ods_dispatcher" && executor === "response_team" && priority === "emergency");
}

export function canClaimRequest(actorGroup: ExecutorGroup, requestGroup: ExecutorGroup, assigneeId: string | undefined, status: string): boolean {
  return actorGroup === requestGroup && !assigneeId && !["completed", "rejected"].includes(status);
}

export function riskLabel(level: RiskLevel): string {
  return {
    black: "Событие сейчас",
    red: "Риск в течение 6 часов",
    yellow: "Риск в течение 12 часов",
    green: "Риск в течение 24 часов"
  }[level];
}

export function alertKindLabel(kind: AlertKind): string {
  return kind === "malfunction" ? "Технический сбой" : "Пожарный риск";
}

export function splitPickets(channels: Channel[]): { located: Channel[]; withoutPicket: Channel[] } {
  return {
    located: channels.filter((channel) => channel.picketSortKey != null).sort((a, b) => a.picketSortKey! - b.picketSortKey!),
    withoutPicket: channels.filter((channel) => channel.picketSortKey == null)
  };
}

export function picketPosition(value: number, keys: number[]): number {
  if (!keys.length) return 390;
  const min = Math.min(...keys);
  const max = Math.max(...keys);
  if (min === max) return 390;
  if (value <= min) return 50;
  if (value >= max) return 730;
  return 50 + ((value - min) / (max - min)) * 680;
}

export const levelName: Record<RiskLevel, string> = {
  black: "Чёрный",
  red: "Красный",
  yellow: "Жёлтый",
  green: "Зелёный"
};

export const requestStatusName = {
  new: "Новая",
  under_review: "На рассмотрении",
  scheduled: "Запланирована",
  in_progress: "В работе",
  completed: "Выполнена",
  rejected: "Отменена"
} as const;

const smsRoleName: Record<string, string> = {
  Technician: "Техник",
  technician: "Техник",
  DistrictDispatcher: "Диспетчер района",
  district_dispatcher: "Диспетчер района",
  OdsDispatcher: "Диспетчер ОДС",
  ods_dispatcher: "Диспетчер ОДС",
  ResponseTeam: "Группа реагирования",
  response_team: "Группа реагирования"
};

export function smsRoleLabel(role: string): string {
  return smsRoleName[role] ?? role;
}

export const smsDeliveryStatusName: Record<SmsDeliveryStatus, string> = {
  delivered: "Доставлено",
  failed: "Недоставлено"
};

export const smsProcessingStatusName: Record<SmsProcessingStatus, string> = {
  undelivered: "Недоставлено",
  new: "Свободная заявка",
  in_progress: "Взято в работу",
  completed: "Выполнено",
  cancelled: "Отменено"
};

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}
