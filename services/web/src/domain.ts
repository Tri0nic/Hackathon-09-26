import type { AlertKind, Channel, RiskLevel } from "./types";

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
  rejected: "Отклонена"
} as const;

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}
