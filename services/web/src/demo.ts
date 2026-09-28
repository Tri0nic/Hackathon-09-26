import type { AppData, Channel } from "./types";

const channels: Channel[] = [
  { id: "temp-1250", name: "Температура ПК 12+50", sensorType: "Температура", picketRaw: "12+50", picketSortKey: 12.5, value: "68 °C", state: "danger", deviceAgeYears: 4.2, ageSource: "generated_demo", maintenanceNote: "ТО 15.08.2026", metadataSource: "demo" },
  { id: "smoke-1270", name: "Дым ПК 12+70", sensorType: "Дым", picketRaw: "12+70", picketSortKey: 12.7, value: "Обнаружен дым", state: "danger", deviceAgeYears: 3.5, ageSource: "generated_demo", maintenanceNote: "ТО 20.07.2026", metadataSource: "demo" },
  { id: "gas-1290", name: "Газ ПК 12+90", sensorType: "Газ", picketRaw: "12+90", picketSortKey: 12.9, value: "0,7%", state: "warning", deviceAgeYears: 5.1, ageSource: "first_seen", maintenanceNote: "ТО 02.06.2026", metadataSource: "computed" },
  { id: "service-free", name: "Служебный канал без пикета", sensorType: "Диагностика", picketSortKey: null, value: "Нет связи", state: "malfunction", deviceAgeYears: 2, ageSource: "generated_demo", maintenanceNote: "Данные не предоставлены", metadataSource: "demo" }
];

const alerts: AppData["alerts"] = [
  {
    id: "8d6fc5a1-06ef-49ee-839c-fb17d121d6cb", episodeId: "EP-2026-0927-014", objectId: "demo-object-1", objectName: "Коллектор №1 · участок Северный", kind: "fire", level: "red", horizon: "6h", probability: 0.82,
    pNow: 0.18, p6h: 0.82, p12h: 0.88, p24h: 0.93, calculatedAt: "2026-09-27T12:42:00+03:00", modelVersion: "catboost-e87d5604945b", stale: false, current: true, picketFrom: 12.5, picketTo: 12.9, channels,
    factors: [
      { label: "Рост температуры", contribution: 0.34, detail: "+29 °C к суточному профилю" },
      { label: "Сигнал дыма", contribution: 0.28, detail: "3 срабатывания за 15 минут" },
      { label: "Газовая концентрация", contribution: 0.12, detail: "Рост в 2,1 раза за час" }
    ],
    recommendation: "Проверить участок ПК 12+50–12+90 и состояние пожарных датчиков в течение 30 минут.",
    context: "Демонстрационный контекст: на соседнем участке запланированы сварочные работы 27.09 с 12:00 до 16:00.",
    recipients: ["Техник", "Диспетчер района", "Диспетчер ОДС"],
    history: [{ toLevel: "green", changedAt: "2026-09-27T11:30:00+03:00" }, { fromLevel: "green", toLevel: "yellow", changedAt: "2026-09-27T11:50:00+03:00" }, { fromLevel: "yellow", toLevel: "red", changedAt: "2026-09-27T12:10:00+03:00" }, { fromLevel: "red", toLevel: "black", changedAt: "2026-09-27T12:30:00+03:00" }, { fromLevel: "black", toLevel: "red", changedAt: "2026-09-27T12:42:00+03:00" }],
    decisions: []
  },
  {
    id: "a4d9a282-c3a2-4fcb-ae19-97341cda46c9", episodeId: "EP-2026-0927-009", objectId: "demo-object-2", objectName: "Коллектор №4 · участок Восточный", kind: "fire", level: "yellow", horizon: "12h", probability: 0.67,
    pNow: 0.09, p6h: 0.38, p12h: 0.67, p24h: 0.72, calculatedAt: "2026-09-27T12:31:00+03:00", modelVersion: "catboost-e87d5604945b", stale: false, current: true, channels: [{ ...channels[3], id: "service-east" }], factors: [{ label: "Потеря связи", contribution: 0.44, detail: "Нет данных 47 минут" }], recommendation: "Проверить питание и линию связи датчика.", context: "Данные о работах не предоставлены.", recipients: ["Диспетчер района", "Диспетчер ОДС"], history: [{ toLevel: "yellow", changedAt: "2026-09-27T12:31:00+03:00" }], decisions: []
  },
  {
    id: "3c2d6307-33ac-40f4-a8c2-80ae9df140a7", episodeId: "EP-2026-0927-004", objectId: "demo-object-3", objectName: "Коллектор №7 · участок Центральный", kind: "fire", level: "green", horizon: "24h", probability: 0.41,
    pNow: 0.03, p6h: 0.14, p12h: 0.25, p24h: 0.41, calculatedAt: "2026-09-27T12:14:00+03:00", modelVersion: "catboost-e87d5604945b", stale: false, current: true, channels: [channels[0]], factors: [{ label: "Температурный тренд", contribution: 0.18, detail: "+6 °C за 3 часа" }], recommendation: "Продолжить наблюдение.", context: "Данные о работах не предоставлены.", recipients: ["Диспетчер ОДС"], history: [{ toLevel: "green", changedAt: "2026-09-27T12:14:00+03:00" }], decisions: [{ decision: "Наблюдение", decidedAt: "2026-09-27T12:18:00+03:00" }]
  },
  {
    id: "44444444-4444-4444-4444-444444444444", episodeId: "EP-DEMO-BLACK", objectId: "demo-object-4", objectName: "Коллектор №9 · участок Южный", kind: "fire", level: "black", horizon: "now", probability: 0.91,
    pNow: 0.91, p6h: 0.94, p12h: 0.96, p24h: 0.98, calculatedAt: "2026-09-27T12:48:00+03:00", modelVersion: "catboost-e87d5604945b", stale: false, current: true, picketFrom: 12.7, picketTo: 12.7, channels: [channels[1]], factors: [{ label: "Дым и быстрый нагрев", contribution: 0.61, detail: "Совместный пожарный паттерн" }], recommendation: "Немедленно проверить участок и направить группу реагирования.", context: "Демонстрационный сценарий BLACK.", recipients: ["Техник", "Диспетчер района", "Диспетчер ОДС", "Группа реагирования"], history: [{ toLevel: "black", changedAt: "2026-09-27T12:48:00+03:00" }], decisions: []
  }
];

export const demoData: AppData = {
  demo: true,
  objects: [
    { id: "demo-object-1", name: "Коллектор №1 · участок Северный", district: "САО", channelCount: 34, level: "red", probability: 0.82, channels },
    { id: "demo-object-2", name: "Коллектор №4 · участок Восточный", district: "ВАО", channelCount: 27, level: "yellow", probability: 0.67, channels: [{ ...channels[3], id: "service-east" }] },
    { id: "demo-object-3", name: "Коллектор №7 · участок Центральный", district: "ЦАО", channelCount: 41, level: "green", probability: 0.41, channels: [channels[0]] },
    { id: "demo-object-4", name: "Коллектор №9 · участок Южный", district: "ЮАО", channelCount: 22, level: "black", probability: 0.91, channels: [channels[1]] }
  ],
  alerts,
  requests: [
    { id: "REQ-1044", publicId: "01044", alertId: alerts[3].id, objectId: "demo-object-4", objectName: alerts[3].objectName, picket: "12+70", recommendation: alerts[3].recommendation, requestKind: "emergency", executorGroup: "response_team", priority: "emergency", description: "Немедленно проверить источник задымления", creatorRole: "ods_dispatcher", comments: [], status: "new", createdAt: "2026-09-27T12:49:00+03:00", updatedAt: "2026-09-27T12:49:00+03:00" },
    { id: "REQ-1043", publicId: "01043", alertId: alerts[0].id, objectId: "demo-object-1", objectName: alerts[0].objectName, picket: "12+50", recommendation: alerts[0].recommendation, requestKind: "repair", executorGroup: "technician", priority: "high", description: "Проверить перегрев и пожарные датчики", creatorRole: "district_dispatcher", assigneeId: "tech-ivanov", assigneeName: "Илья Сергеевич Иванов", comments: [{ id: "COMMENT-1", employeeId: "tech-ivanov", employeeName: "Илья Сергеевич Иванов", text: "Проверил питание датчиков, приступаю к диагностике линии.", createdAt: "2026-09-27T12:46:00+03:00" }], status: "in_progress", createdAt: "2026-09-27T12:43:00+03:00", updatedAt: "2026-09-27T12:45:00+03:00" },
    { id: "REQ-1042", publicId: "01042", alertId: alerts[2].id, objectId: "demo-object-3", objectName: alerts[2].objectName, picket: "12+50", recommendation: "Проверить температурный датчик", requestKind: "inspection", executorGroup: "technician", priority: "normal", description: "Проверить температурный датчик", creatorRole: "district_dispatcher", comments: [], status: "new", createdAt: "2026-09-27T12:20:00+03:00", updatedAt: "2026-09-27T12:24:00+03:00" }
  ],
  sms: [
    { id: "SMS-2201", requestId: "REQ-1043", episodeId: alerts[0].episodeId, episodeTitle: "Перегрев и задымление на Северном участке", alertLevel: "red", recipientId: "tech-ivanov", role: "Техник", recipientName: "Илья Сергеевич Иванов", sentAt: "2026-09-27T12:43:05+03:00", content: "Создана заявка: проверить перегрев и пожарные датчики", incidentSummary: "Рост температуры и сигнал дыма", assigneeName: "Илья Сергеевич Иванов", status: "delivered", processingStatus: "in_progress" },
    { id: "SMS-2202", requestId: "REQ-1043", episodeId: alerts[0].episodeId, episodeTitle: "Перегрев и задымление на Северном участке", alertLevel: "red", recipientId: "tech-petrova", role: "Техник", recipientName: "Мария Андреевна Петрова", sentAt: "2026-09-27T12:43:05+03:00", content: "Создана заявка: проверить перегрев и пожарные датчики", incidentSummary: "Рост температуры и сигнал дыма", status: "failed", processingStatus: "undelivered" },
    { id: "SMS-2204", requestId: "REQ-1044", episodeId: alerts[3].episodeId, episodeTitle: "Критическое задымление на Южном участке", alertLevel: "black", recipientId: "response-orlova", role: "Группа реагирования", recipientName: "Наталья Викторовна Орлова", sentAt: "2026-09-27T12:49:05+03:00", content: "Создана экстренная заявка: немедленно проверить источник задымления", incidentSummary: "Дым и быстрый нагрев", status: "delivered", processingStatus: "new" },
    { id: "SMS-2205", requestId: "REQ-1044", episodeId: alerts[3].episodeId, episodeTitle: "Критическое задымление на Южном участке", alertLevel: "black", recipientId: "tech-sokolov", role: "Техник", recipientName: "Алексей Дмитриевич Соколов", sentAt: "2026-09-27T12:49:05+03:00", content: "Создана экстренная заявка: немедленно проверить источник задымления", incidentSummary: "Дым и быстрый нагрев", status: "delivered", processingStatus: "new" }
  ],
  metrics: { modelVersion: "catboost-e87d5604945b", labelSource: "Синтетическая разметка (не подтверждённые пожары)", rocAuc: 0.9965, precision: 0.8767, recall: 0.7752, alertsPerDay: 0 }
};
