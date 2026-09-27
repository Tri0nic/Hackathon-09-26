import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { App } from "./App";
import { demoData } from "./demo";

test("полная карточка предупреждения сохраняет ключевые блоки", () => {
  const html = renderToStaticMarkup(
    <App initialData={demoData} initialPath={`/alerts/${demoData.alerts[0].id}`} />
  );

  expect(html).toContain("Динамика вероятности");
  expect(html).toContain("Возраст и ТО");
  expect(html).toContain("Решение диспетчера");
  expect(html).toContain("Статусы SMS");
  expect(html).toContain("Демонстрационный контекст");
});

test("карточка использует цвет фактического уровня риска", () => {
  const data = structuredClone(demoData);
  data.alerts[0].level = "black";

  const html = renderToStaticMarkup(
    <App initialData={data} initialPath={`/alerts/${data.alerts[0].id}`} />
  );

  expect(html).toContain("risk-score level-black");
});

test("шапка позволяет выбрать одну из четырёх пользовательских ролей", () => {
  const html = renderToStaticMarkup(<App initialData={demoData} initialPath="/" />);

  expect(html).toContain('aria-label="Текущая роль"');
  expect(html).toContain("Техник");
  expect(html).toContain("Диспетчер района");
  expect(html).toContain("Диспетчер ОДС");
  expect(html).toContain("Группа реагирования");
});
