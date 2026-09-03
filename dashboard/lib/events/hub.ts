export type HubEvent = {
  id: string;
  type: string;
  data: unknown;
};

export class HubSubscription {
  private readonly queue: HubEvent[] = [];
  private readonly waiters: ((event: HubEvent | null) => void)[] = [];
  private closed = false;

  next(): Promise<HubEvent | null> {
    if (this.queue.length) {
      return Promise.resolve(this.queue.shift() || null);
    }
    if (this.closed) {
      return Promise.resolve(null);
    }
    return new Promise((resolve) => this.waiters.push(resolve));
  }

  push(event: HubEvent): void {
    if (this.closed) {
      return;
    }
    const waiter = this.waiters.shift();
    if (waiter) {
      waiter(event);
      return;
    }
    this.queue.push(event);
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    while (this.waiters.length) {
      this.waiters.shift()?.(null);
    }
    this.queue.length = 0;
  }

  queueSize(): number {
    return this.queue.length;
  }
}

type EventHubOptions = {
  maxQueue?: number;
};

export class EventHub {
  private readonly subscriptions = new Set<HubSubscription>();
  private readonly maxQueue: number;

  constructor(options: EventHubOptions = {}) {
    this.maxQueue = Math.max(1, options.maxQueue ?? 100);
  }

  subscribe(): HubSubscription {
    const subscription = new HubSubscription();
    this.subscriptions.add(subscription);
    return subscription;
  }

  publish(event: HubEvent): void {
    for (const subscription of this.subscriptions) {
      const before = subscription.queueSize();
      if (before >= this.maxQueue) {
        subscription.close();
        this.subscriptions.delete(subscription);
        continue;
      }
      subscription.push(event);
    }
  }

  remove(subscription: HubSubscription): void {
    subscription.close();
    this.subscriptions.delete(subscription);
  }
}
