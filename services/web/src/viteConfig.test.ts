import { describe, expect, test } from "vitest";
import { resolveConfig } from "vite";

describe("Vite development server", () => {
  test("proxies API requests to the backend", async () => {
    const config = await resolveConfig({}, "serve", "development");

    expect(config.server.proxy).toMatchObject({
      "/api": { target: "http://localhost:5000", changeOrigin: true }
    });
  });
});
