import { expect, test } from "vitest";
import { api, normalizeApiData } from "./api";

test("узкий API-контракт деградирует в безопасные UI-значения", () => {
  const data = normalizeApiData({
    objects: [{ id: "object-1", name: "Объект 1", channelCount: 3 }],
    alerts: [{ id: "alert-1", episodeId: "episode-1", objectId: "object-1", objectName: "Объект 1", level: "red", horizon: "6h", probability: 0.8, calculatedAt: "2026-09-27T12:00:00Z", modelVersion: "v1", stale: false, current: true }],
    requests: [], sms: [], metrics: {}
  });

  expect(data.objects[0].channels).toEqual([]);
  expect(data.objects[0].district).toBe("Не указан");
  expect(data.alerts[0].kind).toBe("fire");
  expect(data.alerts[0].context).toBe("Данные не предоставлены.");
  expect(data.metrics.labelSource).toContain("Proxy");
});

test("недоставленное SMS техника из API не переходит в обработку", () => {
  const data = normalizeApiData({
    objects: [{ id: "object-1", name: "Коллектор №1", channelCount: 3 }],
    alerts: [{ id: "alert-1", episodeId: "episode-1", objectId: "object-1", objectName: "Коллектор №1", kind: "malfunction", level: "yellow", horizon: "12h", probability: 0.8, calculatedAt: "2026-09-27T12:00:00Z", modelVersion: "v1", stale: false, current: true, factors: [{ label: "Потеря связи", contribution: 0.4, detail: "Нет данных 20 минут" }] }],
    requests: [],
    sms: [{ id: "sms-1", episodeId: "episode-1", alertLevel: "yellow", recipientId: "tech-ivanov", role: "Technician", recipientName: "Илья Сергеевич Иванов", sentAt: "2026-09-27T12:01:00Z", content: "Проверить канал", status: "failed", processingStatus: "in_progress" }],
    metrics: {}
  });

  expect(data.sms[0]).toMatchObject({
    episodeTitle: "Пожарный риск · Коллектор №1",
    incidentSummary: "Потеря связи",
    role: "Техник",
    recipientName: "Илья Сергеевич Иванов",
    status: "failed",
    processingStatus: "undelivered"
  });
});

test("API нормализует маршрутизацию и ответственного заявки", () => {
  const data = normalizeApiData({
    objects: [{ id: "object-1", name: "Объект 1", channelCount: 1 }],
    alerts: [],
    requests: [{
      id: "request-1", alertId: "alert-1", objectId: "object-1", recommendation: "Проверить",
      requestKind: "repair", executorGroup: "response_team", priority: "emergency", description: "Обрыв линии",
      creatorRole: "ods_dispatcher", assigneeId: "response-orlova", assigneeName: "Наталья Викторовна Орлова",
      status: "in_progress", createdAt: "2026-09-28T10:00:00Z", updatedAt: "2026-09-28T10:01:00Z"
    }],
    sms: [], metrics: {}
  });

  expect(data.requests[0]).toMatchObject({
    publicId: "00001",
    executorGroup: "response_team", priority: "emergency", description: "Обрыв линии",
    assigneeName: "Наталья Викторовна Орлова"
  });
});

test("создание RED demo-заявки рассылает SMS районным техникам и первый исполнитель забирает её", async () => {
  const before = await api.load();
  const alert = before.alerts[0];
  const request = await api.createRequest({
    alertId: alert.id,
    requestKind: "repair",
    executorGroup: "technician",
    priority: "high",
    description: "Проверить перегрев кабельной линии",
    creatorRole: "district_dispatcher"
  });
  const afterCreate = await api.load();

  const createdSms = afterCreate.sms.filter((sms) => sms.requestId === request.id);
  expect(createdSms).toHaveLength(2);
  expect(createdSms.every((sms) => sms.processingStatus === "new")).toBe(true);
  await api.claimRequest(request.id, { id: "tech-ivanov", name: "Илья Сергеевич Иванов", group: "technician", districts: ["САО"], objectIds: ["demo-object-1"] });
  expect((await api.load()).sms.filter((sms) => sms.requestId === request.id).every((sms) => sms.processingStatus === "in_progress")).toBe(true);
  await expect(api.claimRequest(request.id, { id: "tech-petrova", name: "Мария Андреевна Петрова", group: "technician", districts: ["САО"], objectIds: ["demo-object-1"] })).rejects.toThrow("Заявка уже взята");
});

test("исполнитель оставляет комментарий и снимает заявку с себя в общий пул", async () => {
  const alert = (await api.load()).alerts[1];
  const request = await api.createRequest({ alertId: alert.id, requestKind: "repair", executorGroup: "technician", priority: "normal", description: "Проверить связь", creatorRole: "district_dispatcher" });
  const employee = { id: "tech-petrova", name: "Мария Андреевна Петрова", group: "technician" as const, districts: ["САО"], objectIds: ["demo-object-1"] };
  await api.claimRequest(request.id, employee);

  await api.executeRequestAction(request.id, employee, "release", "Требуется специалист по линии связи");

  const saved = (await api.load()).requests.find((item) => item.id === request.id)!;
  expect(saved).toMatchObject({ status: "new", assigneeId: undefined, assigneeName: undefined });
  expect(saved.comments.at(-1)).toMatchObject({ employeeName: employee.name, text: "Требуется специалист по линии связи" });
});

test("исполнитель завершает свою заявку с отчётом, а чужую изменить не может", async () => {
  const alert = (await api.load()).alerts[0];
  const request = await api.createRequest({ alertId: alert.id, requestKind: "repair", executorGroup: "technician", priority: "high", description: "Заменить датчик", creatorRole: "district_dispatcher" });
  const owner = { id: "tech-ivanov", name: "Илья Сергеевич Иванов", group: "technician" as const, districts: ["САО"], objectIds: ["demo-object-1"] };
  const stranger = { id: "tech-sokolov", name: "Алексей Дмитриевич Соколов", group: "technician" as const, districts: ["ЦАО", "ЮАО"], objectIds: ["demo-object-3", "demo-object-4"] };
  await api.claimRequest(request.id, owner);

  await expect(api.executeRequestAction(request.id, stranger, "cancel", "Не требуется")).rejects.toThrow("Недостаточно прав");
  await api.executeRequestAction(request.id, owner, "complete", "Датчик заменён, показания в норме");

  const saved = (await api.load()).requests.find((item) => item.id === request.id)!;
  expect(saved.status).toBe("completed");
  expect(saved.comments.at(-1)?.text).toBe("Датчик заменён, показания в норме");
});
