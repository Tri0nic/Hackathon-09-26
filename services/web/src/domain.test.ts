import { describe, expect, test } from "vitest";
import { alertKindLabel, allowedNavigation, canClaimRequest, canCreateRequest, countCriticalObjects, createPublicRequestId, dashboardAlerts, dashboardDistrict, employees, picketPosition, probabilityAtHorizon, profileFor, riskLabel, smsRecipientsForAlert, splitPickets } from "./domain";
import { demoData } from "./demo";

describe("riskLabel", () => {
  test("не выдаёт зелёный уровень за безопасное состояние", () => {
    expect(riskLabel("green")).toBe("Риск в течение 24 часов");
    expect(riskLabel("black")).toBe("Событие сейчас");
  });
});

test("горизонт выбирает соответствующую вероятность предупреждения", () => {
  const alert = demoData.alerts[0];

  expect(probabilityAtHorizon(alert, "now")).toBe(alert.pNow);
  expect(probabilityAtHorizon(alert, "6h")).toBe(alert.p6h);
  expect(probabilityAtHorizon(alert, "12h")).toBe(alert.p12h);
  expect(probabilityAtHorizon(alert, "24h")).toBe(alert.p24h);
});

test("панель ОДС фильтрует предупреждения одновременно по району и уровню", () => {
  const alerts = dashboardAlerts(demoData.alerts, demoData.objects, "ЮАО", "black");

  expect(alerts.map((alert) => alert.objectName)).toEqual(["Коллектор №9 · участок Южный"]);
});

test("панель не применяет сохранённый район к районному диспетчеру", () => {
  expect(dashboardDistrict("district_dispatcher", "ЮАО", ["САО"])).toBe("all");
  expect(dashboardDistrict("ods_dispatcher", "ЮАО", ["САО", "ЮАО"])).toBe("ЮАО");
});

test("панель не показывает исторические предупреждения", () => {
  const data = structuredClone(demoData);
  data.alerts[0].current = false;

  expect(dashboardAlerts(data.alerts, data.objects, "all", "all").map((alert) => alert.id)).not.toContain(data.alerts[0].id);
});

test("критические риски считаются по объектам, а не по числу предупреждений", () => {
  const alert = demoData.alerts.find((item) => item.level === "red")!;

  expect(countCriticalObjects([alert, { ...alert, id: "second-alert" }])).toBe(1);
});

test("журнал предупреждений описывает только прогноз пожарного риска", () => {
  expect(alertKindLabel("fire")).toBe("Пожарный риск");
  expect(alertKindLabel("malfunction" as never)).toBe("Пожарный риск");
});

test("профиль сотрудника содержит ФИО, районы и закреплённые объекты", () => {
  const employee = employees.find((item) => item.id === "tech-ivanov")!;
  const profile = profileFor("technician", employee, demoData.objects);

  expect(profile.name).toBe("Илья Сергеевич Иванов");
  expect(profile.districts).toEqual(["САО"]);
  expect(profile.objects.map((item) => item.id)).toEqual(["demo-object-1"]);
});

test("главный диспетчер относится ко всем районам и объектам", () => {
  const profile = profileFor("ods_dispatcher", undefined, demoData.objects);

  expect(profile.districts).toEqual(["САО", "ВАО", "ЦАО", "ЮАО"]);
  expect(profile.objects).toHaveLength(4);
});

test("RED уведомляет районных техников, BLACK — районных техников и ГБР", () => {
  expect(smsRecipientsForAlert("red", "САО").map((item) => item.id)).toEqual(["tech-ivanov", "tech-petrova"]);
  expect(smsRecipientsForAlert("black", "ЮАО").map((item) => item.id)).toEqual(["tech-sokolov", "response-orlova", "response-volkov"]);
  expect(smsRecipientsForAlert("yellow", "ВАО")).toEqual([]);
});

test("публичный номер заявки всегда содержит пять цифр и не повторяется", () => {
  expect(createPublicRequestId(["12345"], () => 0.12345)).toBe("12346");
  expect(createPublicRequestId([], () => 0)).toBe("00000");
});

test("канал без пикета сохраняется в отдельной группе", () => {
  const result = splitPickets([
    { id: "located", name: "Дым ПК 12+50", sensorType: "smoke", picketSortKey: 12.5 },
    { id: "free", name: "Служебный канал", sensorType: "service", picketSortKey: null }
  ]);

  expect(result.located.map((channel) => channel.id)).toEqual(["located"]);
  expect(result.withoutPicket.map((channel) => channel.id)).toEqual(["free"]);
});

test("крайние пикеты занимают всю ширину линейной карты", () => {
  expect(picketPosition(12.5, [12.5, 12.7, 12.9])).toBe(50);
  expect(picketPosition(12.9, [12.5, 12.7, 12.9])).toBe(730);
});

test("роль определяет доступные разделы", () => {
  expect(allowedNavigation("ods_dispatcher")).toContain("/analytics");
  expect(allowedNavigation("district_dispatcher")).not.toContain("/analytics");
  expect(allowedNavigation("technician")).toEqual(["/requests", "/objects", "/profile", "/model-demo"]);
  expect(allowedNavigation("response_team")).toEqual(["/requests", "/objects", "/profile", "/model-demo"]);
  expect(allowedNavigation("ods_dispatcher")).toContain("/model-demo");
  expect(allowedNavigation("district_dispatcher")).toContain("/model-demo");
});

test("исполнитель видит новые демонстрационные объекты своего района", () => {
  const objects = [...demoData.objects, { ...demoData.objects[0], id: "model-demo-held-out-01", name: "Тестовый объект" }];

  expect(profileFor("technician", employees[0], objects).objects.map((item) => item.id)).toContain("model-demo-held-out-01");
});

test("ОДС создаёт только экстренную заявку для ГБР", () => {
  expect(canCreateRequest("ods_dispatcher", "response_team", "emergency")).toBe(true);
  expect(canCreateRequest("ods_dispatcher", "technician", "normal")).toBe(false);
  expect(canCreateRequest("district_dispatcher", "technician", "normal")).toBe(true);
});

test("исполнитель берёт только свободную заявку своей группы", () => {
  expect(canClaimRequest("technician", "technician", undefined, "new")).toBe(true);
  expect(canClaimRequest("technician", "response_team", undefined, "new")).toBe(false);
  expect(canClaimRequest("technician", "technician", "tech-1", "new")).toBe(false);
  expect(canClaimRequest("technician", "technician", undefined, "completed")).toBe(false);
});
