'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { BatchHandle, FileJob, QualityReport, BATCH_STORAGE_KEY, authorization, batchSnapshot, jobDownload, glossaryPairs } from './durable-jobs';
import { runFileQueue } from './document-stream';

import { ModelItem, isAllowedModel, normalizeModelOptions } from './model-options';

interface ActivityLog {
  id: string;
  stage: string;
  message: string;
  timestamp: string;
  progress?: number;
}

const DEFAULT_MODELS: ModelItem[] = [
  { id: "gemini-3.8-flash", name: "Gemini 3.8 Flash" },
  { id: "gemini-3.8-pro", name: "Gemini 3.8 Pro" },
  { id: "gemini-3.7-flash", name: "Gemini 3.7 Flash" },
  { id: "gemini-3.1-flash", name: "Gemini 3.1 Flash" },
  { id: "gemini-3.1-pro", name: "Gemini 3.1 Pro" },
  { id: "gemini-3.0-flash", name: "Gemini 3.0 Flash" },
  { id: "gemini-3.0-pro", name: "Gemini 3.0 Pro" },
  { id: "google-translate", name: "Google Translate (Free)" }
];

export default function Home() {
  const [activeTab, setActiveTab] = useState<'document' | 'text'>('document');
  const [targetLang, setTargetLang] = useState('Japanese');
  const [provider, setProvider] = useState('gemini-3.8-flash');
  const [apiKey, setApiKey] = useState('');
  const [rememberApiKey, setRememberApiKey] = useState(false);
  const [isUpdatingModels, setIsUpdatingModels] = useState(false);
  const [modelUpdateStatus, setModelUpdateStatus] = useState<string | null>(null);
  const [models, setModels] = useState<ModelItem[]>(DEFAULT_MODELS);
  const [sourceText, setSourceText] = useState('');
  const [translatedText, setTranslatedText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [fileResults, setFileResults] = useState<{id: string; name: string; status: string; progress: number; url?: string; filename?: string; error?: string; report?: QualityReport | null}[]>([]);
  const [activeBatch, setActiveBatch] = useState<BatchHandle | null>(null);
  const [batchError, setBatchError] = useState('');
  const [glossary, setGlossary] = useState('');
  const downloaded = useRef<Record<string, {url: string; filename: string}>>({});
  const latestJobs = useRef<FileJob[]>([]);
  const pendingSubmission = useRef<{batch: BatchHandle; form: FormData} | null>(null);
  const downloadUrls = useRef<string[]>([]);
  const batchAbort = useRef<AbortController | null>(null);
  useEffect(() => () => {
    batchAbort.current?.abort();
    downloadUrls.current.forEach(url => URL.revokeObjectURL(url));
  }, []);
  const [isTranslating, setIsTranslating] = useState(false);
  const [progress, setProgress] = useState(0);

  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Browser-local activity history for the current page session.
  const [activityLogs, setActivityLogs] = useState<ActivityLog[]>([]);
  const [isAutoScroll, setIsAutoScroll] = useState<boolean>(true);
  const [currentStage, setCurrentStage] = useState<string>('IDLE');
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll logs
  useEffect(() => {
    if (isAutoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [activityLogs, isAutoScroll]);
  // apiUrl priorities: 1. Environment variable NEXT_PUBLIC_API_URL, 2. Local fallback
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

  const fileInputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const languages = [
    "Chinese (Simplified)",
    "Japanese",
    "English",
    "Spanish",
    "French",
    "German",
    "Korean",
    "Italian",
    "Portuguese",
    "Russian",
  ];

  // Load persistent settings from localStorage on device
  useEffect(() => {
    try {
      // 1. Purge legacy cached models from earlier runs
      localStorage.removeItem('gemini_cached_models');
      localStorage.removeItem('gemini_cached_models_v2');
      localStorage.removeItem('gemini_cached_models_v3');

      const sessionKey = sessionStorage.getItem('gemini_api_key');
      const optedInKey = localStorage.getItem('gemini_api_key');
      const rememberPreference = localStorage.getItem('gemini_remember_api_key') === 'true';
      const savedKey = rememberPreference ? optedInKey : sessionKey || optedInKey;
      if (savedKey) {
        setApiKey(savedKey);
        const remember = rememberPreference && Boolean(optedInKey);
        setRememberApiKey(remember);
        sessionStorage.setItem('gemini_api_key', savedKey);
        if (!remember) {
          // Remove keys saved by older versions that had no persistence opt-in.
          localStorage.removeItem('gemini_api_key');
          localStorage.removeItem('gemini_remember_api_key');
        }
      }
      const savedProvider = localStorage.getItem('gemini_provider');
      if (savedProvider && isAllowedModel(savedProvider)) {
        setProvider(savedProvider);
      } else {
        setProvider("gemini-3.8-flash");
        localStorage.setItem('gemini_provider', "gemini-3.8-flash");
      }

      // Use versioned cache key v4 as immediate local fallback
      const cachedModels = localStorage.getItem('gemini_cached_models_v4');
      if (cachedModels) {
        const parsed = JSON.parse(cachedModels);
        if (Array.isArray(parsed) && parsed.length > 0) {
          const valid = normalizeModelOptions(parsed);
          if (valid.length > 0) {
            setModels(valid);
            localStorage.setItem('gemini_cached_models_v4', JSON.stringify(valid));
          }
        }
      }

      // Fetch permanent shared model list from backend (Cloud Storage / Server cache) for any user
      fetch(`${apiUrl}/models`)
        .then(res => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then(data => {
          if (data && data.models && Array.isArray(data.models) && data.models.length > 0) {
            const valid = normalizeModelOptions(data.models);
            if (valid.length > 0) {
              const finalList = valid;
              setModels(finalList);
              localStorage.setItem('gemini_cached_models_v4', JSON.stringify(finalList));
            }
          }
        })
        .catch(err => {
          console.warn("Could not sync shared models from server, using local fallback:", err);
        });

    } catch (e) {
      console.warn("Could not load from localStorage:", e);
    }
  }, [apiUrl]);

  const handleApiKeyChange = (val: string) => {
    setApiKey(val);
    try {
      if (val.trim()) {
        sessionStorage.setItem('gemini_api_key', val.trim());
        if (rememberApiKey) localStorage.setItem('gemini_api_key', val.trim());
        else localStorage.removeItem('gemini_api_key');
      } else {
        sessionStorage.removeItem('gemini_api_key');
        localStorage.removeItem('gemini_api_key');
      }
    } catch (e) {
      console.warn("Could not save to localStorage:", e);
    }
  };

  const handleClearApiKey = () => {
    setApiKey('');
    try {
      sessionStorage.removeItem('gemini_api_key');
      localStorage.removeItem('gemini_api_key');
    } catch (e) {
      console.warn("Could not remove from localStorage:", e);
    }
  };

  const handleRememberApiKeyChange = (remember: boolean) => {
    setRememberApiKey(remember);
    try {
      if (remember) {
        localStorage.setItem('gemini_remember_api_key', 'true');
        if (apiKey.trim()) localStorage.setItem('gemini_api_key', apiKey.trim());
      } else {
        localStorage.removeItem('gemini_api_key');
        localStorage.removeItem('gemini_remember_api_key');
      }
    } catch (e) {
      console.warn('Could not update the browser key-storage preference:', e);
    }
  };

  const handleDownloadActivityLog = () => {
    const content = activityLogs.map(entry => `[${entry.timestamp}] [${entry.stage}] ${entry.message}`).join('\n');
    const url = URL.createObjectURL(new Blob([content], {type: 'text/plain;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'translation-session.log';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const handleProviderChange = (val: string) => {
    setProvider(val);
    try {
      localStorage.setItem('gemini_provider', val);
    } catch (e) {
      console.warn("Could not save provider to localStorage:", e);
    }
  };

  const handleUpdateModels = async () => {
    if (!apiKey.trim()) {
      alert("Please enter your Gemini API Key first so we can query your account's available models.");
      return;
    }
    setIsUpdatingModels(true);
    setModelUpdateStatus("Fetching models...");
    try {
      const formData = new FormData();
      formData.append('api_key', apiKey.trim());
      const res = await fetch(`${apiUrl}/models`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Failed to fetch models');
      }
      const data = await res.json();
      if (data.models && Array.isArray(data.models) && data.models.length > 0) {
        const updatedList = normalizeModelOptions(data.models);
        setModels(updatedList);
        localStorage.setItem('gemini_cached_models_v4', JSON.stringify(updatedList));
        setModelUpdateStatus(`✓ ${updatedList.length} models updated in this browser`);
        setTimeout(() => setModelUpdateStatus(null), 5000);
      } else {
        setModelUpdateStatus("No models found");
        setTimeout(() => setModelUpdateStatus(null), 3000);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      alert(`Could not update models: ${msg}`);
      setModelUpdateStatus("Failed to update");
      setTimeout(() => setModelUpdateStatus(null), 3000);
    } finally {
      setIsUpdatingModels(false);
    }
  };

  // Timer: counts elapsed seconds while translating
  useEffect(() => {
    if (isTranslating) {
      const t0 = Date.now();
      setElapsedSeconds(0);
      timerRef.current = setInterval(() => {
        setElapsedSeconds(Math.floor((Date.now() - t0) / 1000));
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [isTranslating]);

  // Estimate remaining time from elapsed time and current progress
  const estimatedRemaining = (): string => {
    if (progress <= 5 || elapsedSeconds < 2) return 'estimating...';
    const rate = progress / elapsedSeconds; // percent per second
    const remaining = Math.max(0, (100 - progress) / rate);
    const seconds = Math.ceil(remaining);
    return `~${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  };

  const handleTextTranslate = async () => {
    if (!sourceText.trim()) return;
    setIsTranslating(true);
    setTranslatedText('Translating...');

    try {
      const formData = new FormData();
      formData.append('text', sourceText);
      formData.append('target_lang', targetLang);
      formData.append('provider', provider);
      if (apiKey) formData.append('api_key', apiKey);

      const response = await fetch(`${apiUrl}/translate/text`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        let errorMsg = 'Translation failed';
        try {
          const errorData = await response.json();
          errorMsg = errorData.detail || errorMsg;
        } catch {
          errorMsg = `${response.status} ${response.statusText}`;
        }
        throw new Error(errorMsg);
      }
      const data = await response.json();
      setTranslatedText(data.translated_text);
    } catch (error) {
      setTranslatedText(`Error (URL: ${apiUrl}): ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setIsTranslating(false);
    }
  };

  const getStageBadgeStyle = (stage: string) => {
    switch (stage.toUpperCase()) {
      case 'INIT':
        return { bg: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: 'rgba(56, 189, 248, 0.3)' };
      case 'EXTRACT':
        return { bg: 'rgba(6, 182, 212, 0.15)', color: '#22d3ee', border: 'rgba(6, 182, 212, 0.3)' };
      case 'TRANSLATE':
        return { bg: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', border: 'rgba(168, 85, 247, 0.3)' };
      case 'REVIEW':
        return { bg: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' };
      case 'RENDER':
        return { bg: 'rgba(16, 185, 129, 0.15)', color: '#34d399', border: 'rgba(16, 185, 129, 0.3)' };
      case 'COMPLETE':
        return { bg: 'rgba(34, 197, 94, 0.2)', color: '#4ade80', border: 'rgba(34, 197, 94, 0.4)' };
      case 'ERROR':
        return { bg: 'rgba(239, 68, 68, 0.2)', color: '#f87171', border: 'rgba(239, 68, 68, 0.4)' };
      default:
        return { bg: 'rgba(148, 163, 184, 0.15)', color: '#cbd5e1', border: 'rgba(148, 163, 184, 0.3)' };
    }
  };

  const monitorBatch = useCallback(async (batch: BatchHandle) => {
    batchAbort.current?.abort();
    const controller = new AbortController();
    batchAbort.current = controller;
    setActiveBatch(batch);
    setIsTranslating(true);
    setBatchError('');
    let previousMessages = '';
    try {
      while (!controller.signal.aborted) {
        const snapshot = await batchSnapshot(apiUrl, batch, controller.signal);
        latestJobs.current = snapshot.jobs;
        setFileResults(snapshot.jobs.map(job => ({id: job.id, name: job.filename, status: job.state, progress: job.progress,
          ...downloaded.current[job.id], error: job.state === 'failed' ? job.message : undefined, report: job.report})));
        await runFileQueue(snapshot.jobs, async job => {
          if (job.artifact && !downloaded.current[job.id]) {
            try {
              const download = await jobDownload(apiUrl, batch, job, 'artifact', controller.signal);
              downloaded.current[job.id] = download;
              downloadUrls.current.push(download.url);
              setFileResults(previous => previous.map(result => result.id === job.id ? {...result, ...download} : result));
              if (job.state === 'passed') {
                const link = document.createElement('a');
                link.href = download.url;
                link.download = download.filename;
                document.body.appendChild(link);
                link.click();
                link.remove();
              }
            } catch (error) {
              if (controller.signal.aborted) throw error;
              setBatchError('A file is ready, but its download failed. Reconnect to retry.');
            }
          }
        });
        setFileResults(snapshot.jobs.map(job => ({
          id: job.id, name: job.filename, status: job.state, progress: job.progress,
          ...downloaded.current[job.id], error: job.state === 'failed' ? job.message : undefined,
          report: job.report,
        })));
        setProgress(snapshot.jobs.reduce((sum, job) => sum + job.progress, 0) / Math.max(1, snapshot.jobs.length));
        const messages = snapshot.jobs.map(job => `${job.filename}: ${job.message || job.state}`).join('\n');
        if (messages !== previousMessages) {
          previousMessages = messages;
          setActivityLogs(previous => [...previous.slice(-199), {id: crypto.randomUUID(), stage: 'REVIEW', message: messages, timestamp: new Date().toLocaleTimeString()}]);
        }
        if (snapshot.finished || snapshot.jobs.every(job => ['waiting_credentials', 'passed', 'needs_review', 'failed', 'cancelled'].includes(job.state))) {
          setCurrentStage(snapshot.jobs.some(job => job.state !== 'passed') ? 'REVIEW' : 'COMPLETE');
          break;
        }
        setCurrentStage('TRANSLATE');
        await new Promise<void>(resolve => {
          const finish = () => {clearTimeout(timer); controller.signal.removeEventListener('abort', finish); resolve();};
          const timer = setTimeout(finish, 1500);
          controller.signal.addEventListener('abort', finish, {once: true});
        });
      }
    } catch (error) {
      if (!controller.signal.aborted) setBatchError(`${error instanceof Error ? error.message : 'Connection lost.'} Processing continues on the server. Use Reconnect.`);
    } finally {
      if (batchAbort.current === controller) setIsTranslating(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(BATCH_STORAGE_KEY);
      if (saved) {
        const batch = JSON.parse(saved) as BatchHandle;
        if (typeof batch.id === 'string' && typeof batch.token === 'string') void monitorBatch(batch);
      }
    } catch { localStorage.removeItem(BATCH_STORAGE_KEY); }
    return () => batchAbort.current?.abort();
  }, [monitorBatch]);

  const handleDocumentTranslate = async () => {
    if (!files.length || isTranslating) return;
    setBatchError('');
    let terms: Record<string, string>;
    try { terms = glossaryPairs(glossary); }
    catch (error) { setBatchError(error instanceof Error ? error.message : 'Invalid glossary.'); return; }
    const batch = {id: crypto.randomUUID(), token: crypto.randomUUID() + crypto.randomUUID()};
    const form = new FormData();
    files.forEach(file => form.append('files', file));
    form.append('batch_id', batch.id);
    form.append('access_token', batch.token);
    form.append('target_lang', targetLang);
    form.append('provider', provider);
    form.append('glossary', JSON.stringify(terms));
    if (apiKey) form.append('api_key', apiKey);
    downloadUrls.current.forEach(url => URL.revokeObjectURL(url));
    downloadUrls.current = [];
    downloaded.current = {};
    setFileResults([]);
    setIsTranslating(true);
    setActiveBatch(batch);
    localStorage.setItem(BATCH_STORAGE_KEY, JSON.stringify(batch));
    pendingSubmission.current = {batch, form};
    try {
      const response = await fetch(`${apiUrl}/jobs/batches`, {method: 'POST', body: form});
      if (!response.ok) {
        const detail = await response.json();
        throw new Error(detail.detail || `Submission failed (${response.status}).`);
      }
      pendingSubmission.current = null;
      await monitorBatch(batch);
    } catch (error) {
      setBatchError(error instanceof Error ? error.message : 'Submission failed. Reconnect to check whether it was accepted.');
      setIsTranslating(false);
    }
  };

  const retrySubmission = async () => {
    const pending = pendingSubmission.current;
    if (!pending) return;
    setIsTranslating(true);
    try {
      const response = await fetch(`${apiUrl}/jobs/batches`, {method: 'POST', body: pending.form});
      if (!response.ok) throw new Error(`Upload retry failed (${response.status}).`);
      pendingSubmission.current = null;
      await monitorBatch(pending.batch);
    } catch (error) {
      setBatchError(error instanceof Error ? error.message : 'Upload retry failed.');
      setIsTranslating(false);
    }
  };

  const controlBatch = async (action: 'cancel' | 'resume') => {
    if (!activeBatch) return;
    try {
      const form = new FormData();
      if (apiKey) form.append('api_key', apiKey);
      const response = await fetch(`${apiUrl}/jobs/batches/${activeBatch.id}/${action}`, {method: 'POST', headers: authorization(activeBatch), body: form});
      if (!response.ok) throw new Error(`${action} failed (${response.status}).`);
      await monitorBatch(activeBatch);
    } catch (error) {setBatchError(error instanceof Error ? error.message : 'Job action failed.');}
  };

  return (
    <div className="container">
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
        <h1 className="title" style={{ margin: 0 }}>Context-Aware Document Translator</h1>
        <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="btn" title="Open Google AI Studio to create a Gemini API key">Get Gemini API key</a>
        <a
          href="https://github.com/henryhyunwookim/multi-language-document-translator"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            color: '#94a3b8',
            textDecoration: 'none',
            fontSize: '0.9rem',
            transition: 'color 0.2s',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = '#e2e8f0')}
          onMouseLeave={e => (e.currentTarget.style.color = '#94a3b8')}
        >
          <svg height="20" width="20" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
              0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
              -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66
              .07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15
              -.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27
              .68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
              .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48
              0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
          </svg>
          GitHub
        </a>
      </div>

      <div className="glass-card">
        {/* Settings Bar */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
          <div className="input-group">
            <label className="label">Target Language</label>
            <select value={targetLang} onChange={(e) => setTargetLang(e.target.value)}>
              {languages.map(lang => <option key={lang} value={lang}>{lang}</option>)}
            </select>
          </div>
          <div className="input-group">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
              <label className="label" style={{ margin: 0 }}>AI Model</label>
              <button
                type="button"
                onClick={handleUpdateModels}
                disabled={isUpdatingModels}
                style={{
                  background: 'rgba(59, 130, 246, 0.15)',
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  borderRadius: '6px',
                  color: '#93c5fd',
                  fontSize: '0.75rem',
                  padding: '3px 8px',
                  cursor: isUpdatingModels ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  transition: 'all 0.2s',
                }}
                title="Fetch latest models from Google Gemini API"
              >
                <span style={{ display: 'inline-block', transform: isUpdatingModels ? 'rotate(360deg)' : 'none', transition: 'transform 0.8s ease' }}>🔄</span>
                {isUpdatingModels ? 'Updating...' : 'Update Models'}
              </button>
            </div>
            <select value={provider} onChange={(e) => handleProviderChange(e.target.value)}>
              {models.map(m => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            {modelUpdateStatus && (
              <span style={{ fontSize: '0.75rem', color: modelUpdateStatus.startsWith('✓') ? '#4ade80' : '#f87171', marginTop: '3px' }}>
                {modelUpdateStatus}
              </span>
            )}
          </div>
          {!provider.toLowerCase().includes('google') && (
            <div className="input-group">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                <label className="label" style={{ margin: 0 }}>Gemini API Key</label>
                {apiKey && (
                  <span style={{ fontSize: '0.72rem', color: '#4ade80', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span>{rememberApiKey ? '🔒 Remembered on this device' : '🔒 Kept for this tab'}</span>
                    <button
                      type="button"
                      onClick={handleClearApiKey}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: '#f87171',
                        cursor: 'pointer',
                        fontSize: '0.72rem',
                        padding: 0,
                        textDecoration: 'underline'
                      }}
                      title="Clear saved key from this browser"
                    >
                      Clear
                    </button>
                  </span>
                )}
              </div>
              <input
                type="password"
                placeholder="Paste your Gemini API key (kept in this tab by default)..."
                value={apiKey}
                onChange={(e) => handleApiKeyChange(e.target.value)}
              />
              <label style={{display: 'flex', gap: '0.45rem', alignItems: 'center', marginTop: '0.4rem', color: '#94a3b8', fontSize: '0.75rem'}}>
                <input type="checkbox" checked={rememberApiKey} onChange={e => handleRememberApiKeyChange(e.target.checked)} />
                Remember this key in this browser (shared-device users should leave this off)
              </label>
            </div>
          )}
        </div>

        {/* Tabs */}
        <div className="tabs">
          <div
            className={`tab ${activeTab === 'document' ? 'active' : ''}`}
            onClick={() => setActiveTab('document')}
          >
            Document
          </div>
          <div
            className={`tab ${activeTab === 'text' ? 'active' : ''}`}
            onClick={() => setActiveTab('text')}
          >
            Instant Text
          </div>
        </div>

        {/* Document Tab Content */}
        {activeTab === 'document' && (
          <div className="fade-in">
            <div
              className="upload-zone"
              onClick={() => !isTranslating && fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                if (!isTranslating && e.dataTransfer.files.length) {
                  setFiles(Array.from(e.dataTransfer.files));
                }
              }}
            >
              <input
                type="file"
                hidden
                ref={fileInputRef}
                multiple disabled={isTranslating} onChange={(e) => setFiles(Array.from(e.target.files || []))}
                accept=".pptx,.xlsx,.docx,.pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.csv,.json,.html,.htm"
              />
              <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>📄</div>
              <h3>{files.length ? files.map(file => file.name).join(', ') : 'Drop files here or click to browse'}</h3>
              <p style={{ color: '#94a3b8', marginTop: '0.5rem' }}>Supports PPTX, XLSX, DOCX, PDF, Images (PNG/JPG/WEBP), TXT, MD, CSV, JSON, HTML</p>
            </div>

            <button
              className="btn"
              style={{ width: '100%' }}
              title="Translate the selected documents"
              onClick={handleDocumentTranslate}
              disabled={!files.length || isTranslating}
            >
              {isTranslating ? 'Processing...' : 'Translate Documents'}
            </button>

            <label className="label" style={{marginTop: '1rem'}}>Glossary (optional; one source term = translated term per line)</label>
            <textarea value={glossary} onChange={event => setGlossary(event.target.value)} disabled={isTranslating} placeholder="company name = preferred translation" style={{height: '80px'}} />
            {batchError && <p role="alert" style={{color: '#f87171'}}>{batchError}</p>}
            {pendingSubmission.current && !isTranslating && <button type="button" className="btn" title="Retry uploading the selected files" onClick={() => void retrySubmission()}>Retry upload</button>}
            {activeBatch && <div style={{display: 'flex', flexWrap: 'wrap', gap: '0.75rem', marginTop: '1rem'}}>
              <button type="button" className="btn" title="Reconnect to this batch and refresh its progress" onClick={() => void monitorBatch(activeBatch)}>Reconnect</button>
              <button type="button" className="btn" title="Resume files that failed or were cancelled" onClick={() => void controlBatch('resume')} disabled={isTranslating}>Resume failed/cancelled files</button>
              <button type="button" className="btn" title="Stop the active translation batch" onClick={() => void controlBatch('cancel')} disabled={!isTranslating}>Cancel batch</button>
            </div>}
            {progress > 0 && (
              <div style={{ marginTop: '1.25rem' }}>
                {/* Label row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem', fontSize: '0.85rem', color: '#94a3b8' }}>
                  <span>
                    {progress < 100
                      ? isTranslating
                        ? `Translating… ${Math.floor(elapsedSeconds / 60)}:${String(elapsedSeconds % 60).padStart(2, '0')} elapsed`
                        : 'Translation complete'
                      : 'Batch finished — see each file below'}
                  </span>
                  <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {Math.round(progress)}%
                    {isTranslating && progress < 100 && ` · ${estimatedRemaining()} remaining`}
                  </span>
                </div>
                {/* Progress bar */}
                <div className="status-bar">
                  <div
                    className="progress"
                    style={{
                      width: `${progress}%`,
                      transition: 'width 2s ease-out',
                    }}
                  />
                </div>
              </div>
            )}

            {/* Live Activity Stream Console */}
            {(isTranslating || activityLogs.length > 0) && (
              <div style={{
                marginTop: '1.25rem',
                background: 'rgba(10, 15, 30, 0.75)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '10px',
                overflow: 'hidden',
                boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.37)'
              }}>
                {/* Console Header */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '0.6rem 1rem',
                  background: 'rgba(15, 23, 42, 0.6)',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
                  fontSize: '0.8rem',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                    <span style={{
                      display: 'inline-block',
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background: isTranslating ? '#22c55e' : '#94a3b8',
                      boxShadow: isTranslating ? '0 0 8px #22c55e' : 'none',
                    }} />
                    <span style={{ fontWeight: 600, color: '#e2e8f0', letterSpacing: '0.02em' }}>
                      Live Activity Stream
                    </span>
                    {currentStage && currentStage !== 'IDLE' && (
                      <span style={{
                        padding: '0.15rem 0.5rem',
                        borderRadius: '4px',
                        fontSize: '0.72rem',
                        fontWeight: 600,
                        letterSpacing: '0.04em',
                        background: getStageBadgeStyle(currentStage).bg,
                        color: getStageBadgeStyle(currentStage).color,
                        border: `1px solid ${getStageBadgeStyle(currentStage).border}`
                      }}>
                        {currentStage}
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.8rem' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.75rem', color: '#94a3b8', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={isAutoScroll}
                        onChange={e => setIsAutoScroll(e.target.checked)}
                        style={{ cursor: 'pointer' }}
                      />
                      Auto-scroll
                    </label>
                    <button
                      type="button"
                      title="Clear the displayed activity log"
                      onClick={() => setActivityLogs([])}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: '#64748b',
                        fontSize: '0.75rem',
                        cursor: 'pointer',
                        padding: '0.2rem 0.4rem',
                        borderRadius: '4px',
                        transition: 'color 0.15s'
                      }}
                      onMouseEnter={e => (e.currentTarget.style.color = '#cbd5e1')}
                      onMouseLeave={e => (e.currentTarget.style.color = '#64748b')}
                    >
                      Clear
                    </button>
                    <button
                      type="button"
                      onClick={handleDownloadActivityLog}
                      title="Download activity shown in this browser session"
                      className="btn-secondary"
                    >
                      Download Session Log
                    </button>
                  </div>
                </div>

                {/* Console Log Rows */}
                <div style={{
                  maxHeight: '220px',
                  overflowY: 'auto',
                  padding: '0.75rem 1rem',
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                  fontSize: '0.8rem',
                  lineHeight: 1.6,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.35rem'
                }}>
                  {activityLogs.length === 0 ? (
                    <div style={{ color: '#64748b', fontStyle: 'italic' }}>Waiting for translation activity...</div>
                  ) : (
                    activityLogs.map((item) => {
                      const badge = getStageBadgeStyle(item.stage);
                      return (
                        <div key={item.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem' }}>
                          <span style={{ color: '#64748b', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                            {item.timestamp}
                          </span>
                          <span style={{
                            padding: '0.05rem 0.4rem',
                            borderRadius: '3px',
                            fontSize: '0.7rem',
                            fontWeight: 600,
                            letterSpacing: '0.03em',
                            flexShrink: 0,
                            background: badge.bg,
                            color: badge.color,
                            border: `1px solid ${badge.border}`
                          }}>
                            {item.stage}
                          </span>
                          <span style={{ color: '#e2e8f0', wordBreak: 'break-word' }}>
                            {item.message}

                          </span>
                        </div>
                      );
                    })
                  )}
                  <div ref={logsEndRef} />
                </div>
              </div>
            )}

            <div aria-live="polite" style={{marginTop: '1rem'}}>
              {fileResults.map((result, index) => (
                <div key={result.id || index} style={{padding: '0.75rem', borderBottom: '1px solid #334155'}}>
                  <strong>{result.name}</strong> — {result.status.replaceAll('_', ' ')}
                  {['queued', 'running'].includes(result.status) && ` (${Math.round(result.progress)}%)`}
                  {result.error && <p style={{color: '#f87171'}}>{result.error}</p>}
                  {result.status === 'waiting_credentials' && <p>Re-enter your API key above, then choose Resume.</p>}
                  {result.url && <a className="btn" style={{marginLeft: '1rem'}} href={result.url} download={result.filename}>Download</a>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Text Tab Content */}
        {activeTab === 'text' && (
          <div className="fade-in">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
              <div>
                <label className="label">Source Text</label>
                <textarea
                  style={{ height: '300px' }}
                  placeholder="Paste your content..."
                  value={sourceText}
                  onChange={(e) => setSourceText(e.target.value)}
                />
              </div>
              <div>
                <label className="label">Translation</label>
                <textarea
                  style={{ height: '300px', background: 'rgba(15, 23, 42, 0.2)' }}
                  readOnly
                  value={translatedText}
                />
              </div>
            </div>
            <button
              className="btn"
              style={{ width: '100%', marginTop: '1.5rem' }}
              title="Translate the source text"
              onClick={handleTextTranslate}
              disabled={isTranslating || !sourceText}
            >
              {isTranslating ? 'Translating...' : 'Translate Now'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
