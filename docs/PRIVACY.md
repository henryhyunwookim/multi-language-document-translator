# Privacy and data handling

This document describes the current behavior of the hosted web demo. A separately hosted copy may have different storage, logging, retention, and provider settings; its operator is responsible for publishing accurate terms for that deployment.

## What you send

The browser sends the text or uploaded document, target language, selected model, and (for Gemini) your API key to the configured translator backend over HTTPS. Gemini requests are made with your key. Google Translate requests use the selected provider. Provider processing is governed by the provider's own terms and privacy policy.

The key is held in browser session storage by default and is sent with translation/model requests. You can explicitly opt in to persistent local storage. Clear the key when finished, and do not opt in on shared devices. The backend does not persist visitor Gemini keys in its job database or use the maintainer's key for Cloud Run visitor requests.

## Temporary files and operational data

Uploaded data is processed by the backend. Durable batch jobs store source files, generated artifacts, and quality reports on the backend's job directory until their configured TTL (24 hours by default); deployments using ephemeral instance storage can lose job data earlier after an instance restart. Synchronous output artifacts can be written to the configured temporary output directory and to the GCS `document-translator/outputs/` prefix for large downloads. Their actual retention depends on the deployed bucket lifecycle policy, which the operator must verify.

New operational audit records are written to `document-translator/run_log.json` and Cloud Logging. They contain status, provider, language, duration, output size, and success/failure metadata. Older records from earlier revisions may also contain filenames and exception text; the audit file retains up to 1,000 recent records. Application diagnostics may contain exception details; access to Cloud Logging and the state bucket is restricted to the operator's Google Cloud project. Batch status, reports, and artifacts are protected by a random per-batch access token.

The hosted demo does not provide user accounts or promise long-term storage, backup, or confidentiality suitable for regulated or sensitive records. Avoid uploading confidential documents until you have reviewed the host's retention configuration and the selected provider's policies.

## Browser-side storage

The browser caches model names and preferences in local storage. Gemini API keys are session-only unless you check “Remember this key in this browser,” which stores the key in that browser's local storage. Browser storage is accessible to scripts running on the site and is not encrypted by this application.
