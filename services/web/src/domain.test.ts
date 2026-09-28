import { describe, expect, test } from "vitest";
import { alertKindLabel, allowedNavigation, canClaimRequest, canCreateRequest, createPublicRequestId, employees, picketPosition, profileFor, riskLabel, smsRecipientsForAlert, splitPickets } from "./domain";
import { demoData } from "./demo";

describe("riskLabel", () => {
  test("не выдаёт зелёный уровень за безопасное состояние", () => {
    expect(riskLabel("green")).toBe("Риск в течение 24 часов");
    expect(riskLabel("black")).toBe("Событие сейчас");
  });
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
  expect(allowedNavigation("technician")).toEqual(["/requests", "/objects", "/profile"]);
  expect(allowedNavigation("response_team")).toEqual(["/requests", "/objects", "/profile"]);
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
