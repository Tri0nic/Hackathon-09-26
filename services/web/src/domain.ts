import type { Alert, AlertKind, Channel, Employee, ExecutorGroup, RequestPriority, RiskLevel, RiskObject, SensorReading, SmsDeliveryStatus, SmsProcessingStatus, UserRole } from "./types";

export type DashboardHorizon = "now" | "6h" | "12h" | "24h";

export const employees: Employee[] = [
  { id: "tech-ivanov", name: "Илья Сергеевич Иванов", group: "technician", districts: ["САО"], objectIds: ["demo-object-1"] },
  { id: "tech-petrova", name: "Мария Андреевна Петрова", group: "technician", districts: ["САО"], objectIds: ["demo-object-1"] },
  { id: "tech-sokolov", name: "Алексей Дмитриевич Соколов", group: "technician", districts: ["ЦАО", "ЮАО"], objectIds: ["demo-object-3", "demo-object-4"] },
  { id: "response-orlova", name: "Наталья Викторовна Орлова", group: "response_team", districts: ["ЮАО"], objectIds: ["demo-object-4"] },
  { id: "response-volkov", name: "Сергей Павлович Волков", group: "response_team", districts: ["ЮАО"], objectIds: ["demo-object-4"] }
];

const dispatcherProfiles = {
  district_dispatcher: { name: "Елена Викторовна Смирнова", districts: ["САО"] },
  ods_dispatcher: { name: "Александр Михайлович Кузнецов", districts: undefined }
} as const;

export function profileFor(role: UserRole, employee: Employee | undefined, objects: RiskObject[]) {
  if (employee) {
    return { name: employee.name, role, districts: employee.districts, objects: objects.filter((item) => employee.objectIds.includes(item.id) || employee.districts.includes(item.district)) };
  }
  const dispatcher = dispatcherProfiles[role as keyof typeof dispatcherProfiles];
  const districts = dispatcher?.districts ? [...dispatcher.districts] : [...new Set(objects.map((item) => item.district))];
  return { name: dispatcher?.name ?? "Сотрудник", role, districts, objects: objects.filter((item) => districts.includes(item.district)) };
}

export function visibleObjectsFor(role: UserRole, employee: Employee | undefined, objects: RiskObject[]): RiskObject[] {
  return profileFor(role, employee, objects).objects;
}

export function smsRecipientsForAlert(level: RiskLevel, district: string): Employee[] {
  if (level !== "red" && level !== "black") return [];
  return employees.filter((employee) => employee.districts.includes(district) && (employee.group === "technician" || level === "black"));
}

export function createPublicRequestId(existing: string[], random: () => number = Math.random): string {
  const used = new Set(existing);
  let candidate = Math.floor(random() * 100000) % 100000;
  for (let attempt = 0; attempt < 100000; attempt += 1) {
    const value = candidate.toString().padStart(5, "0");
    if (!used.has(value)) return value;
    candidate = (candidate + 1) % 100000;
  }
  throw new Error("Свободные номера заявок закончились");
}

export function allowedNavigation(role: UserRole): string[] {
  if (role === "ods_dispatcher") return ["/", "/objects", "/alerts", "/requests", "/analytics", "/sms", "/profile", "/model-demo"];
  if (role === "district_dispatcher") return ["/", "/objects", "/alerts", "/requests", "/sms", "/profile", "/model-demo"];
  return ["/requests", "/objects", "/profile", "/model-demo"];
}

export function canCreateRequest(role: UserRole, level: RiskLevel, executor: ExecutorGroup, priority: RequestPriority): boolean {
  return role === "district_dispatcher" || (role === "ods_dispatcher" && (level !== "black" || (executor === "response_team" && priority === "emergency")));
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

export function probabilityAtHorizon(alert: Alert, horizon: DashboardHorizon): number {
  return {
    now: alert.pNow,
    "6h": alert.p6h,
    "12h": alert.p12h,
    "24h": alert.p24h
  }[horizon];
}

export function dashboardAlerts(
  alerts: Alert[],
  objects: RiskObject[],
  district: string,
  level: RiskLevel | "all"
): Alert[] {
  const objectIds = new Set(objects.filter((object) => district === "all" || object.district === district).map((object) => object.id));
  return alerts.filter((alert) => alert.current && objectIds.has(alert.objectId) && (level === "all" || alert.level === level));
}

export function dashboardDistrict(role: UserRole, selected: string, districts: string[]): string {
  return role === "ods_dispatcher" && districts.includes(selected) ? selected : "all";
}

export function countCriticalObjects(alerts: Alert[]): number {
  return new Set(alerts.filter((alert) => alert.level === "black" || alert.level === "red").map((alert) => alert.objectId)).size;
}

export function alertKindLabel(kind: AlertKind): string {
  void kind;
  return "Пожарный риск";
}

export function splitPickets(channels: Channel[]): { located: Channel[]; withoutPicket: Channel[] } {
  return {
    located: channels.filter((channel) => channel.picketSortKey != null).sort((a, b) => a.picketSortKey! - b.picketSortKey!),
    withoutPicket: channels.filter((channel) => channel.picketSortKey == null)
  };
}

export function buildSensorHistory(channel: Channel, end = new Date("2026-09-29T12:00:00Z")): SensorReading[] {
  const rawValue = channel.value ?? "Нет данных";
  const numericMatch = rawValue.replace(",", ".").match(/-?\d+(?:\.\d+)?/);
  const current = numericMatch ? Number(numericMatch[0]) : undefined;
  const unit = numericMatch ? rawValue.slice(numericMatch.index! + numericMatch[0].length).trim() : "";
  const temperature = channel.sensorType.toLowerCase().includes("температур");
  const gas = channel.sensorType.toLowerCase().includes("газ");
  return Array.from({ length: 21 }, (_, index) => {
    const measuredAt = new Date(end.getTime() - (20 - index) * 6 * 60 * 60 * 1000).toISOString();
    if (current === undefined) {
      const finalReading = index === 20;
      return {
        measuredAt,
        value: finalReading ? rawValue : channel.state === "malfunction" ? "Связь стабильна" : "Норма",
        state: finalReading ? channel.state ?? "normal" : "normal",
      };
    }
    const progress = index / 20;
    const totalRise = temperature && channel.state === "danger" ? 29 : gas ? current * .55 : Math.max(current * .08, 1);
    const wave = index === 20 ? 0 : Math.sin(index * 1.7) * Math.max(totalRise * .04, .1);
    const numericValue = index === 20 ? current : current - totalRise * (1 - progress) + wave;
    const rounded = temperature ? Math.round(numericValue) : Math.round(numericValue * 100) / 100;
    return {
      measuredAt,
      numericValue: rounded,
      value: `${String(rounded).replace(".", ",")}${unit ? ` ${unit}` : ""}`,
      state: index === 20 ? channel.state ?? "normal" : index >= 18 && channel.state !== "normal" ? "warning" : "normal",
    };
  });
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
  in_progress: "В работе",
  completed: "Выполнена",
  rejected: "Отклонена"
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
