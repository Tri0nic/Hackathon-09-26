import { expect, test } from "vitest";
import { normalizeApiData } from "./api";

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
