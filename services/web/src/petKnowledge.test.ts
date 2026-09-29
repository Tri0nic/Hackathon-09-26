import { describe, expect, test } from "vitest";
import { answerPetQuestion } from "./petKnowledge";

describe("answerPetQuestion", () => {
  test("объясняет, как создать заявку", () => {
    const answer = answerPetQuestion("Как создать заявку по предупреждению?", "/alerts");

    expect(answer.found).toBe(true);
    expect(answer.text).toContain("Создать заявку");
  });

  test("использует текущий раздел для общего вопроса", () => {
    const answer = answerPetQuestion("Что здесь можно сделать?", "/objects/demo-object-1");

    expect(answer.found).toBe(true);
    expect(answer.text).toContain("объекта");
  });

  test("не выдаёт случайный ответ на неизвестный или пустой запрос", () => {
    expect(answerPetQuestion("квантовый телепорт", "/").found).toBe(false);
    expect(answerPetQuestion("   ", "/alerts").found).toBe(false);
  });
});
