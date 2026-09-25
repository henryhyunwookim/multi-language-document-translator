export interface BatchHandle { id: string; token: string }
export interface Finding { code: string; message: string; severity: string; location?: string; segment_id?: string }
export interface QualityReport { status: string; checks: Record<string, string>; findings: Finding[] }
export interface FileJob {
  id: string; filename: string; state: string; progress: number; message: string;
  artifact: boolean; report: QualityReport | null;
}
export interface BatchSnapshot { id: string; jobs: FileJob[]; finished: boolean }

export const BATCH_STORAGE_KEY = 'translator_active_batch_v1';

export function authorization(batch: BatchHandle) {
  return { Authorization: `Bearer ${batch.token}` };
}

export function glossaryPairs(text: string): Record<string, string> {
  const entries: [string, string][] = [];
  for (const line of text.split('\n').filter(line => line.trim())) {
    const separator = line.indexOf('=');
    if (separator <= 0 || !line.slice(separator + 1).trim()) throw new Error('Use one source term = translated term per glossary line.');
    entries.push([line.slice(0, separator).trim(), line.slice(separator + 1).trim()]);
  }
  return Object.fromEntries(entries);
}

export async function batchSnapshot(apiUrl: string, batch: BatchHandle, signal: AbortSignal): Promise<BatchSnapshot> {
  const response = await fetch(`${apiUrl}/jobs/batches/${batch.id}`, {headers: authorization(batch), signal, cache: 'no-store'});
  if (!response.ok) throw new Error(`Batch status unavailable (${response.status}).`);
  return response.json();
}

export async function jobDownload(apiUrl: string, batch: BatchHandle, job: FileJob, type: 'artifact' | 'report', signal?: AbortSignal) {
  const response = await fetch(`${apiUrl}/jobs/batches/${batch.id}/${job.id}/${type}`, {headers: authorization(batch), signal});
  if (!response.ok) throw new Error(`Download unavailable (${response.status}).`);
  const extension = job.filename.split('.').pop()?.toLowerCase() || '';
  const outputExtension = ['png', 'jpg', 'jpeg', 'webp'].includes(extension) ? 'md' : extension;
  const filename = type === 'report' ? `${job.filename}.quality.json` : `${job.filename.replace(/\.[^.]+$/, '')}_translated.${outputExtension}`;
  return {url: URL.createObjectURL(await response.blob()), filename};
}
