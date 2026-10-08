/**
 * In-process BroadcastChannel: a message reaches every other open channel of
 * the same name on a later task, never the sender. A channel the test opens
 * stands in for another tab.
 */
export class FakeBroadcastChannel extends EventTarget {
  private static open = new Set<FakeBroadcastChannel>();
  readonly name: string;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(name: string) {
    super();
    this.name = name;
    FakeBroadcastChannel.open.add(this);
  }

  postMessage(data: unknown): void {
    if (!FakeBroadcastChannel.open.has(this)) throw new DOMException('closed', 'InvalidStateError');
    const copy: unknown = structuredClone(data);
    for (const peer of FakeBroadcastChannel.open) {
      if (peer === this || peer.name !== this.name) continue;
      setTimeout(() => {
        const event = new MessageEvent('message', { data: copy });
        peer.onmessage?.(event);
        peer.dispatchEvent(event);
      }, 0);
    }
  }

  close(): void {
    FakeBroadcastChannel.open.delete(this);
  }
}

/** A channel standing in for another tab, recording what it receives. */
export function otherTab(name = 'geolens-auth') {
  const channel = new FakeBroadcastChannel(name);
  const received: unknown[] = [];
  channel.addEventListener('message', (event) => received.push((event as MessageEvent).data));
  return {
    received,
    post: (data: unknown) => channel.postMessage(data),
    close: () => channel.close(),
  };
}
