export interface ModelItem {
  id: string;
  name: string;
}

export function isAllowedModel(value: string): boolean {
  const lower = value.toLowerCase();
  if (lower.includes('google translate') || lower === 'google-translate') return true;
  const excluded = [
    'nano', 'banana', '8b', 'exp', 'experimental', 'thinking', 'learnlm', 'gemma',
    'embed', 'audio', 'tts', 'imagen', 'robotics', 'custom', 'preview-0', 'tuning',
  ];
  return !excluded.some(word => lower.includes(word)) && (lower.includes('pro') || lower.includes('flash'));
}

/** Normalize both legacy cache strings and API records before storing UI state. */
export function normalizeModelOptions(items: unknown[]): ModelItem[] {
  const unique = new Map<string, ModelItem>();
  for (const item of items) {
    let id: string;
    let name: string;
    if (typeof item === 'string') {
      name = item.trim();
      id = name.toLowerCase().replace(/\s+/g, '-');
    } else if (item && typeof item === 'object' && 'id' in item && typeof item.id === 'string') {
      id = item.id.trim();
      name = 'name' in item && typeof item.name === 'string' ? item.name.trim() || id : id;
    } else {
      continue;
    }
    if (!id) continue;
    if (/^google[ -]translate(?:\s*\(free\))?$/i.test(id) || /^google translate(?:\s*\(free\))?$/i.test(name)) {
      id = 'google-translate';
      name = 'Google Translate (Free)';
    }
    if ((isAllowedModel(id) || isAllowedModel(name)) && !unique.has(id)) {
      unique.set(id, { id, name });
    }
  }
  if (!unique.has('google-translate')) {
    unique.set('google-translate', { id: 'google-translate', name: 'Google Translate (Free)' });
  }
  return [...unique.values()];
}
