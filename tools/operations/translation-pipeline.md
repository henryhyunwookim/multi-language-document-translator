# Running the reviewed translation pipeline

## Local Windows launch

From the repository root in PowerShell:

```powershell
# First run on a new machine; creates an isolated .venv and installs frontend dependencies.
.\tools\operations\run-local.ps1 -Mode Setup

# Check dependencies, desktop GUI initialization, and real PPTX/XLSX/DOCX rendering.
.\tools\operations\run-local.ps1 -Mode Check

# Start both the API and web UI; Ctrl+C stops both process trees.
.\tools\operations\run-local.ps1

# Or use the desktop interface.
.\tools\operations\run-local.ps1 -Mode Desktop
```

The web UI opens at `http://127.0.0.1:3000`; API documentation is at
`http://127.0.0.1:8080/docs`. The launcher prints log locations and detects startup
failures. Use `-ApiPort 8081 -WebPort 3001` if the default ports are occupied.
No virtual-environment activation is required. If PowerShell blocks local script
execution, invoke `powershell -ExecutionPolicy Bypass -File .\tools\operations\run-local.ps1`
(the exception applies only to that process).

Prerequisites are Python 3.11+, Node.js/npm, and LibreOffice. Install LibreOffice
with `winget install --id TheDocumentFoundation.LibreOffice --exact`; the launcher
and renderer detect its standard Windows installation automatically. Set
`OFFICE_RENDERER` for a custom installation. The local checks do not use a model
API or require cloud credentials. Actual Gemini translation requires an API key
entered in the app, `GEMINI_API_KEY`, or the existing Secret Manager setup.

Jobs persist under `%LOCALAPPDATA%\DocumentTranslator\jobs`, and each launch writes
logs under `%LOCALAPPDATA%\DocumentTranslator\logs`. The launcher connects the web
UI to the chosen local API port, even if a cloud API URL was previously configured.
Shared feedback remains optional; use `TRANSLATION_FEEDBACK_BUCKET` as described below.

The web application submits files to persistent jobs. Each file gets an
independent state, artifact and quality report. Closing or refreshing the page
does not cancel server work; the browser retains the batch capability and can
reconnect. Only artifacts with status `passed` automatically trigger downloads.
Files marked `needs_review` expose a manual download and their findings.

## Quality states

| State | Meaning | Artifact |
| --- | --- | --- |
| `queued` / `running` | Waiting for a worker or processing | Not ready |
| `waiting_credentials` | A user-supplied API key was lost during process restart | Resume with the key |
| `passed` | All applicable configured checks completed without unresolved findings | Downloadable |
| `needs_review` | A check was unavailable, confidence was low, or defects/capability limits remain | Downloadable with report |
| `failed` | A hard invariant, translation coverage, input validation or processing step failed | Withheld |
| `cancelled` | Cancellation was requested and observed | Withheld |
| `expired` | Retention period ended | Access denied; files removed |

`passed` is not a guarantee of perfect translation. It records the outcome of the
specified checks. Reports include the inspected manifest, plan, source locations,
findings, check outcomes, repair count and model-call count. Summary polling omits
the full manifest; the downloadable report includes it.

## Server configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRANSLATOR_JOB_DIR` | OS temporary directory / `translator-jobs`; `/data/translator-jobs` in Docker | SQLite database, input copies and output artifacts |
| `TRANSLATOR_JOB_TTL` | `86400` | Batch/artifact lifetime in seconds, measured from submission |
| `TRANSLATOR_JOB_WORKERS` | `2` | Maximum concurrently running files across workers sharing the store |
| `TRANSLATOR_PROVIDER_WORKERS` | `2` | Concurrent file limit per provider |
| `OFFICE_RENDERER` | `soffice` / `libreoffice` from PATH | LibreOffice executable for source/output PDF rendering |
| `TRANSLATOR_REVIEW_MODEL` | Selected translation model | Separate model identifier for independent review calls |
| `TRANSLATION_FEEDBACK_BUCKET` | Unset (disabled) | Existing GCS bucket for shared, versioned failure-code memory |

## Components and reconstruction

The downloadable manifest includes component categories and locations. Native
Office text distinguishes table cells, shape text, worksheet names, slide notes
and comments. Raster assets start as `image_unknown`; available vision models
classify their regions as text, table, image containing text, pure image, diagram
or unknown. Vision boxes use normalized coordinates; native PDF boxes use page
points. Classification is evidence, not proof that every image label was translated:
embedded Office/PDF images remain preserved assets with explicit review findings.

Native PDFs use detected table cell boundaries for translation and placement,
including empty/merged-cell geometry, while retaining original vector rules and
artwork. Tables without detectable boundaries still require visual review.
Scanned-page classifiers pass a component inventory to reconstruction agents.

PowerPoint slide notes are translated as native text; slide-number fields remain
protected. When rendered review detects overflow, the pipeline first tries a
15% reduction of the existing DrawingML text scale on the affected slides,
with a minimum scale of 55% of the nominal font size. It keeps shape geometry
and run styling. The candidate must pass structural and rendered review,
including readability, before replacing the prior artifact. If that fails,
the existing meaning-preserving wording repair is tried under the same gates.
Without a working Office renderer and visual reviewer, fit is not certified.

Excel worksheet names are translated, sanitized to Excel constraints, and made
unique without regard to case. Direct qualifiers in formulas, defined names,
chart formulas, table formulas, pivot worksheet sources and internal hyperlinks
are updated. Formula string literals are preserved. Dynamic references such as
`INDIRECT`, external consumers, and opaque connections can require review.
The legacy lightweight adapter used by offline preservation fixtures retains its
old behavior; production translation uses the quality-enabled adapter.

## Shared failure memory

Set `TRANSLATION_FEEDBACK_BUCKET` to the same existing bucket on each service or
machine. Use application-default credentials with object create, get and list
permissions on `translation-feedback/`; avoid an ephemeral upload bucket whose
lifecycle policy deletes this prefix. This change does not provision a bucket,
change IAM, or deploy service configuration.

Each observed supported failure writes a create-only record at
`translation-feedback/v1/<format>/<failure-code>.json`. Records contain only
schema version, format and an allowlisted failure code: no source text, filenames,
translations, exception messages or agent-generated instructions. Concurrent
writers cannot overwrite an existing record. Every new supervisor loads the
records and enables corresponding built-in review checks and translation
guidance. The selected rules also participate in checkpoint invalidation.
Offline or inaccessible storage falls back to the normal local quality gates.

This is shared failure prevention, not unrestricted self-modifying software.
Agent findings may be imperfect; shared observations can strengthen checks but
cannot disable invariants or install generated fixes. New repair strategies need
regression tests and a code release. No system can promise that an error will
never recur. To roll back a shared observation, an operator can remove its
specific record; workers already processing a file retain their initial rules.

## Provider error recovery

Supervised model calls automatically resume the rejected request after HTTP
`Retry-After`, Google `RetryInfo`, or a reported retry delay. When no delay is
available, exponential backoff grows from 15 seconds to at most five minutes
between attempts. Waiting continues until success or cancellation, including
long quota windows, and reports progress once per minute. Cancellation is checked
each second. Quota rejections do not consume additional logical model-call budget.
Temporary connection failures (including DNS failures and timeouts) and HTTP
408/500/502/503/504 responses retry the same request up to three times, waiting
2, 4 and 8 seconds. These waits are cancellable and do not consume additional
logical model calls. Authentication and invalid-request errors are not retried.
If retries are exhausted, existing drafts remain checkpointed and the report
identifies provider unavailability. Missing translations or unresolved protected
entities still block delivery; an outage never bypasses quality checks.

Failed jobs show the failed checks and record the failure in the application log.
After connectivity is restored, choose **Resume failed/cancelled files** in the
web tool to reuse saved drafts and rerun review. A process restart still follows
the normal job/credential recovery path.

The retry behavior follows Google's [retry guidance](https://ai.google.dev/gemini-api/docs/troubleshooting).
Native fitting uses [DrawingML normal autofit](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.normalautofit?view=openxml-3.0.1),
and PDF cell geometry uses [PyMuPDF table detection](https://pymupdf.readthedocs.io/en/latest/page.html#Page.find_tables).

Use a persistent local disk volume for `TRANSLATOR_JOB_DIR`; temporary storage
only survives while the host/container filesystem survives. The Docker image
declares `/data` as a volume. Mount an explicitly named volume or host disk there
for container replacement/restart recovery. Keep the API running with one Uvicorn
process when using user-supplied API keys; the in-process queue uses multiple
worker threads, while credentials intentionally are not shared across processes.

SQLite leases coordinate workers on the same supported local filesystem. Do not
put this database on a GCS/FUSE/NFS mount. Multiple independent Cloud Run
instances do not share its state, and request-scoped CPU allocation may suspend
background workers. This backend is **not a distributed Cloud Run job store**.
Use a persistent single-host service for the durable queue until a distributed
database, object store and continuously scheduled worker implementation is added.
No deployment resources are provisioned by this change.

LibreOffice Writer, Calc, Impress and Noto CJK fonts are included in
`backend/Dockerfile`. Local installations need equivalent tools/fonts. Rendering
uses a separate temporary LibreOffice profile for every input/output pair and a
90-second timeout. Missing/failed rendering is recorded, not bypassed as a pass.

The existing Gemini SDK is retained behind a credential-scoped client factory.
Concurrent jobs no longer obtain their generation client from mutable global API
key configuration. The factory relies on the pinned 0.8.x SDK client field; it
must be reviewed when upgrading that SDK. Model IDs are no longer silently
rewritten to a different version.

## Batch API

`POST /jobs/batches` accepts multipart fields:

- `files`: repeated file parts, 1–20 files, up to 64 MiB each / 256 MiB per batch.
- `batch_id`: a client-generated canonical UUID.
- `access_token`: a random secret of at least 32 characters. The browser creates
  this from two random UUIDs; only its hash is stored in the database.
- `provider`, `target_lang`, optional `api_key`.
- `glossary`: JSON object of source → target terms, at most 200 pairs.

Reusing the same batch ID, token, files and settings returns the existing jobs.
Reusing it with different content/settings is rejected. The browser's Retry
upload action reuses the original submission ID and form.

All subsequent batch endpoints require `Authorization: Bearer <access_token>`:

| Endpoint | Operation |
| --- | --- |
| `GET /jobs/batches/{batch_id}` | Poll per-file states and summary reports |
| `POST /jobs/batches/{batch_id}/cancel` | Cancel unfinished files |
| `POST /jobs/batches/{batch_id}/resume` | Retry failed/cancelled/credential-blocked files; optional multipart `api_key` |
| `GET /jobs/batches/{batch_id}/{job_id}/artifact` | Download a passed or needs-review artifact |
| `GET /jobs/batches/{batch_id}/{job_id}/report` | Download the complete JSON quality report |
| `GET /jobs/capabilities` | Format guarantees, renderer availability and retention settings |

Unauthorized/unknown batches return 404; expired batch capabilities return 410.
Tokens are sent in headers, not download URLs. Browser blob URLs are local to the
page; server-side artifact access expires with the batch. A downloaded copy is
not revoked by server expiry.

## Recovery and cancellation

Jobs claim a renewable 60-second lease. A stopped/crashed worker cannot overwrite
the result of a newer owner. Expired leases return work to the queue; accepted
segment translations survive through checkpoints. Checkpoints are bound to the
source hash, format, target language, model and glossary. Changed inputs or
settings do not reuse incompatible translations.

The checkpoint fingerprint also includes the reviewer model, pipeline version,
and extracted segment boundaries. Draft translations survive review outages but
are stored separately from accepted translations. Cached text is reviewed again;
a new rejection removes its previous acceptance. Checkpoint writes are serialized
across parallel segment batches.

Automatic recovery retains the current call budget. An explicit Resume action
starts a new bounded attempt while preserving accepted translations and recording
the previous call count in the checkpoint. A job with unresolved semantic findings
can produce a needs-review artifact; those findings are not converted into a pass
when its repair limit is reached.

Cancellation is cooperative. It is checked between stages/calls; an in-flight
provider request or renderer may take until its timeout to finish. Cancellation
or lost ownership prevents publication. Graceful worker shutdown releases work
back to the queue. Files already completed remain available independently.

API keys supplied in a request are kept only in memory. Server-managed credentials
can be resolved again after restart; user-key jobs enter `waiting_credentials`
until the key is supplied again. Batch capability tokens are stored in the
browser so it can recover the active batch; clearing browser storage removes that
local handle. The API still permits recovery using a retained ID and token.

## Format contracts and checks

Native Office adapters preserve package members and validate all non-editable XML
and binary payloads. XLSX shared strings may be expanded into equivalent per-cell
inline strings; the validator normalizes both representations before comparing.
Formulas, relationships, object geometry and styling remain protected. Word field
results are preserved because Office may regenerate them.

JSON translation edits string values only; CSV keeps cell positions; HTML keeps
link destinations and excludes code/script/style content; Markdown protects code,
link targets and list/heading markers. Structured-text output does not claim page
layout replication.

The supervisor charges model attempts before calls, including failed requests,
and has a bounded per-document budget, capped at 512 calls. Every response must
return the expected IDs exactly once. Numeric entities and literal URLs are
checked independently. Source-grounded reviewers must account for every reviewed
segment. Up to two targeted semantic repair cycles are permitted.

Native Office translation groups prose across formatting runs while retaining
hyperlink, field, cell and line-break boundaries. An inline typography specialist
maps approved text back to the existing runs. Its output must concatenate exactly
to the approved translation. If alignment fails, a lossless fallback preserves the
text and records an emphasis-review finding instead of silently discarding styles.

Full-width digits are normalized before numeric comparison. Potential date,
time, decimal or scale-unit conversions go to a separate entity reviewer, which
must return an explicit equivalence verdict and evidence for every mismatch.
Unexplained changed values remain hard failures. A reviewer cannot approve a
batch by omitting IDs: malformed responses are retried, then split into smaller
groups within the same call budget. Table and diagram reviewers are routed to
relevant segments rather than every text segment in the document. Repeated
context is sent once per batch, and linguistic prompts exclude raw package XML.

Digital PDFs use their original pages and replace only their text layers. Photos
and vector graphics are protected during redaction. Each replacement is rendered
in isolation and checked for complete glyph coverage before insertion; fit
failures can request a concise, source-reviewed repair. Image-embedded labels
remain a reported capability limit. Scanned/reconstructed PDFs check insertion
results and retry with a compact layout. Blank output pages are hard failures,
including when a model visual reviewer reports no problems.

Office and PDF artifacts receive rendered comparisons when tools are available.
PPT slide clipping can trigger one concise-text repair, followed by semantic,
structural and visual validation again. There is no automatic speculative
Word/Excel page-to-object repair. Original diagram assets, VML and chart caches
are preserved, with their translation limitations recorded explicitly.

Legacy synchronous/SSE document endpoints remain available and include quality
status/report metadata. They do not provide the durable job lifecycle. Desktop
translation uses the shared inspected pipeline and saves a `.quality.json` file
alongside the output, showing needs-review status when applicable.

## Evaluation

```sh
python tools/evaluation/run_evaluation.py
python tools/evaluation/test_multilingual_quality.py
python tools/verification/verify_api_stream.py
node tools/verification/verify_document_stream.cjs
node tools/verification/verify_durable_jobs_ui.cjs
```

Run frontend TypeScript checking and linting with its installed dependencies.
`tools/evaluation/corpus.v1.json` defines the offline regression suites and the real
document cases still needed. `output/evaluation.json` is generated locally and
excluded from Git. Mocked reviewers exercise control flow and acceptance gates;
they do not measure bilingual accuracy or visual quality of live model output.

## Local batch runner

`tools/operations/translate_documents.py` calls the same inspected pipeline as the API and
desktop client. It accepts arbitrary input/language pairs; it contains no sample
filenames, per-document translations or special-case patches.

```sh
python tools/operations/translate_documents.py --model MODEL_ID --output-dir output/batch \
  --job path/to/presentation.pptx English \
  --job path/to/workbook.xlsx Japanese
```

Use `--resume` to load compatible checkpoints, `--review-model MODEL_ID` to select
the independent reviewer, and `--workers` / `--quality-workers` to bound document
and segment concurrency. `--overwrite` is required to replace existing artifacts.
Source files are never overwritten. Every job receives a quality report and
result record; failed artifacts are withheld. Local batch tracing is disabled.
