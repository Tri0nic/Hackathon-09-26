import { describe, expect, test } from "vitest";
import { alertKindLabel, picketPosition, riskLabel, splitPickets } from "./domain";

describe("riskLabel", () => {
  test("не выдаёт зелёный уровень за безопасное состояние", () => {
    expect(riskLabel("green")).toBe("Риск в течение 24 часов");
    expect(riskLabel("black")).toBe("Событие сейчас");
  });
});

test("технический сбой имеет отдельную подпись", () => {
  expect(alertKindLabel("malfunction")).toBe("Технический сбой");
  expect(alertKindLabel("fire")).toBe("Пожарный риск");
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
