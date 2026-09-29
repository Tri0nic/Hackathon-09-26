export type PetAnswer = {
  found: boolean;
  text: string;
  link?: { label: string; href: string };
};

type KnowledgeEntry = PetAnswer & {
  keywords: string[];
  routes: string[];
};

const entries: KnowledgeEntry[] = [
  {
    found: true,
    keywords: ["заявк", "создат", "исполн", "назнач", "работ"],
    routes: ["/requests", "/alerts"],
    text: "Откройте предупреждение и нажмите «Создать заявку». После сохранения она появится в разделе заявок у подходящей группы исполнителей.",
    link: { label: "Перейти к предупреждениям", href: "/alerts" },
  },
  {
    found: true,
    keywords: ["объект", "датчик", "канал", "показан", "сделат"],
    routes: ["/objects"],
    text: "В карточке объекта видны его датчики, текущие показания и история измерений. Нажмите на датчик, чтобы открыть подробный график.",
    link: { label: "Открыть объекты", href: "/objects" },
  },
  {
    found: true,
    keywords: ["предупрежден", "тревог", "риск", "пожар", "прогноз"],
    routes: ["/alerts", "/"],
    text: "В журнале предупреждений собраны текущие оценки пожарного риска. Откройте запись, чтобы увидеть причины, динамику и рекомендации.",
    link: { label: "Открыть предупреждения", href: "/alerts" },
  },
  {
    found: true,
    keywords: ["смс", "sms", "уведомлен", "доставк", "получател"],
    routes: ["/sms"],
    text: "Журнал SMS показывает получателя, причину отправки, доставку и статус обработки уведомления.",
    link: { label: "Открыть журнал SMS", href: "/sms" },
  },
  {
    found: true,
    keywords: ["модел", "демо", "сценар", "расчет", "расчёт"],
    routes: ["/model-demo"],
    text: "В демонстрации модели можно выбрать сценарий, запустить расчёт и передать результат в журнал предупреждений.",
    link: { label: "Открыть демонстрацию", href: "/model-demo" },
  },
  {
    found: true,
    keywords: ["роль", "сотрудник", "профил", "доступ"],
    routes: ["/profile"],
    text: "Роль и сотрудник переключаются в верхней панели. От выбора зависят доступные объекты, заявки и действия.",
  },
];

const fallback: PetAnswer = {
  found: false,
  text: "Я пока знаю только про объекты, предупреждения, заявки, SMS, роли и демонстрацию модели. Попробуйте спросить об одном из этих разделов.",
};

const tokens = (value: string) => value
  .toLocaleLowerCase("ru-RU")
  .replaceAll("ё", "е")
  .match(/[a-zа-я0-9]+/giu)?.filter((token) => token.length > 2) ?? [];

export function answerPetQuestion(query: string, path: string): PetAnswer {
  const queryTokens = tokens(query);
  if (!queryTokens.length) return { ...fallback, text: "Напишите вопрос — например, как создать заявку или где посмотреть датчики." };

  const isContextQuestion = queryTokens.some((token) => ["здесь", "раздел", "сделать", "показано", "страница"].some((word) => token.startsWith(word)));
  let best: { entry: KnowledgeEntry; score: number } | undefined;

  for (const entry of entries) {
    const keywordScore = entry.keywords.reduce(
      (score, keyword) => score + (queryTokens.some((token) => token.startsWith(keyword) || keyword.startsWith(token)) ? 2 : 0),
      0,
    );
    const routeScore = isContextQuestion && entry.routes.some((route) => route === "/" ? path === "/" : path.startsWith(route)) ? 3 : 0;
    const score = keywordScore + routeScore;
    if (score > 0 && (!best || score > best.score)) best = { entry, score };
  }

  if (!best) return fallback;
  const { keywords: _keywords, routes: _routes, ...answer } = best.entry;
  return answer;
}
