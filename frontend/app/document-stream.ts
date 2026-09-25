export interface DocumentEvent {
  type: string;
  stage?: string;
  message?: string;
  progress?: number;
  filename?: string;
  file_b64?: string;
  download_url?: string;
}

/** Consume complete SSE frames, including frames split across network chunks. */
export async function consumeDocumentStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: DocumentEvent) => Promise<void>,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let terminal = false;
  const frame = async (text: string) => {
    const data = text.split(/\r?\n/).filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart()).join('\n');
    if (!data) return;
    const event: DocumentEvent = JSON.parse(data);
    await onEvent(event);
    terminal = event.type === 'complete' || event.type === 'error';
  };
  try {
    while (!terminal) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let separator: RegExpExecArray | null;
      while (!terminal && (separator = /\r?\n\r?\n/.exec(buffer))) {
        const text = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        await frame(text);
      }
      if (done) {
        if (!terminal && buffer.trim()) await frame(buffer);
        break;
      }
    }
    if (!terminal) throw new Error('Connection closed before this file completed.');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

/** Bounded worker queue; each callback handles and records its own file errors. */
export async function runFileQueue<T>(items: T[], run: (item: T, index: number) => Promise<void>, concurrency = 2) {
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (next < items.length) {
      const index = next++;
      await run(items[index], index);
    }
  }));
}
