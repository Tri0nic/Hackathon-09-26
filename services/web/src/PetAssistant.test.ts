import { expect, test } from "vitest";
import { scrollPetChatToBottom } from "./PetAssistant";

test("чат прокручивается к последнему сообщению", () => {
  const container = { scrollTop: 0, scrollHeight: 480 };

  scrollPetChatToBottom(container);

  expect(container.scrollTop).toBe(480);
});
