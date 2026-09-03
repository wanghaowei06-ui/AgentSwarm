import { describe, expect, it } from "vitest";

import { EventHub } from "../lib/events/hub";

describe("EventHub", () => {
  it("delivers a published event to a subscriber and closes cleanly", async () => {
    const hub = new EventHub();
    const subscription = hub.subscribe();
    hub.publish({ id: "matrix:$event", type: "observation", data: { summary: "hello" } });

    await expect(subscription.next()).resolves.toEqual({
      id: "matrix:$event",
      type: "observation",
      data: { summary: "hello" },
    });
    subscription.close();
    await expect(subscription.next()).resolves.toBeNull();
  });

  it("bounds a slow subscriber instead of growing memory forever", async () => {
    const hub = new EventHub({ maxQueue: 1 });
    const subscription = hub.subscribe();
    hub.publish({ id: "one", type: "observation", data: {} });
    hub.publish({ id: "two", type: "observation", data: {} });

    await expect(subscription.next()).resolves.toBeNull();
  });
});
