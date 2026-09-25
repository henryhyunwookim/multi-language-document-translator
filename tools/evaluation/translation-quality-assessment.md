# Translation quality architecture: implementation status

The approved roadmap is now implemented as a bounded translation and review
pipeline with persistent file jobs. The initial assessment found mostly fixed
workflows, output-only critics that could pass after exhausted retries, and
Office reconstruction that discarded unsupported objects. Those findings drove
the changes below.

This implementation does not establish a universal translation-quality claim.
A file is accepted only for the checks actually completed. Unsupported or opaque
content is disclosed, unavailable checks remain visible, and structural failures
withhold the output.

| Roadmap area | Implemented behavior | Primary implementation |
| --- | --- | --- |
| Input understanding | Binary signatures, Office package validation, relationship targets, PDF/image inspection, explicit format capability registry | `backend/quality/inspection.py` |
| Shared representation | Stable IDs, source locations, surrounding context, protected run XML, asset hashes and limitations | `backend/quality/models.py` |
| Bounded planning | Model-selected native/vision routing and review specialists from an allowlist, mandatory gates, confidence and model-call budgets | `backend/quality/supervisor.py` |
| Contextual translation | Per-occurrence IDs, document glossary, exact response-ID validation, independent source-grounded review | `backend/quality/supervisor.py` |
| Native reconstruction | XLSX/PPTX/DOCX package patching; JSON, CSV, HTML, Markdown and text adapters | `backend/handlers/ooxml_text.py`, `backend/quality/text_adapter.py` |
| Structural validation | Independent source/output comparison allowing only designated text changes and equivalent shared-string expansion | `backend/quality/validation.py` |
| Visual validation | LibreOffice rendering, page geometry checks and source/output image review; unavailable rendering is never a pass | `backend/quality/validation.py` |
| Targeted repair | Up to two semantic/entity repair cycles on failed segment IDs; one concise-text repair for PPT slide clipping, followed by review and rendering again | `backend/quality/supervisor.py`, `backend/handlers/ooxml_text.py` |
| Truthful gates | `passed`, `needs_review` and `failed`; exhausted PDF critics retain defects; missing/error pages fail | `backend/agents/nodes.py`, `backend/handlers/pdf_scanned.py` |
| Durable execution | Persistent jobs, leases, checkpoints, idempotent submission, cancellation, recovery, per-provider limits and expiring artifacts | `backend/jobs.py`, `backend/job_api.py` |
| User delivery | Multiple-file uploads, independent downloads, quality reports, reconnection and resume | `frontend/app/page.tsx`, `frontend/app/durable-jobs.ts` |
| Evaluation | Versioned generated fixtures and machine-readable offline results | `tools/evaluation/corpus.v1.json`, `tools/evaluation/run_evaluation.py` |

## What makes this more agentic

The planner can select an allowed processing/review strategy from inspected
content. Translation and independent reviewer calls operate on explicit source
records. Findings select the next repair targets, and results return through
bounded checks before acceptance. Native file writing and hard invariants remain
deterministic. This combines dynamic choices with an auditable workflow rather
than relying on the number of components named agents.

The specialist tool set is intentionally constrained. It is not a general-purpose
agent with unrestricted tools. The distinction between predetermined workflows
and model-selected processes is described in
[LangGraph's workflow and agent guidance](https://docs.langchain.com/oss/python/langgraph/workflows-agents).

## Preservation behavior

- Excel retains shapes, charts, embedded objects, formulas, numeric values, links
  and sheet names. Shared strings are expanded into independent inline cell
  occurrences so repeated words can be translated differently by context.
- PowerPoint retains relationships, hyperlinks, run styling, native shapes and
  geometry. Actual soft breaks remain breaks; `_x000B_` text artifacts become
  spaces. Notes and supported DrawingML labels are included.
- Word now uses package patching too: hyperlinks, tables, headers, footers,
  drawings and fields remain intact. Field-generated text is preserved.
- JSON keys/types, CSV cell positions, HTML link destinations and protected code,
  and Markdown code/link syntax are reconstructed by format-specific adapters.
- Opaque embedded files, bitmap text, VML shapes, and chart caches are preserved
  with explicit review findings. They are not silently represented as translated.

Package patching addresses the unsupported-object loss documented in the
[openpyxl tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html).
PowerPoint's soft-break/run distinction is described in the
[python-pptx text API](https://python-pptx.readthedocs.io/en/stable/api/text.html).

## Remaining capability limits

- Image input currently produces translated Markdown, not a redrawn image.
- Scanned PDFs have source-image review and bounded page gates. Native PDFs still
  lack an exact source-to-output segment map and explicitly report unverified
  coverage. Neither path promises the original PDF's editability.
- Word/Excel visual defects are reported for review; automatic visual text repair
  is limited to PPT slide parts with an unambiguous page-to-part mapping.
- Rendered checks require LibreOffice. The backend Dockerfile includes it and CJK
  fonts. A missing local renderer produces `needs_review`.
- Semantic/visual reviewers are separate calls and can use a separately configured
  review model. They can still miss defects; human evaluation remains necessary.
- Durable jobs currently use SQLite plus local artifact files on a persistent
  volume. This supports one host, not independent Cloud Run replicas or SQLite
  on object-storage/network mounts. A distributed store/worker backend remains
  necessary before horizontal cloud deployment of durable jobs.
- API keys supplied by users are held only in worker memory. After a process
  restart, affected jobs request credentials again and retain their checkpoints.
- The desktop client uses the same inspected artifact pipeline and saves a quality
  report beside each output. Durable multi-file queue controls are in the web UI.

## Verification and further evaluation

Run the versioned offline corpus:

```sh
python tools/evaluation/run_evaluation.py
node tools/verification/verify_document_stream.cjs
node tools/verification/verify_durable_jobs_ui.cjs
python tools/verification/verify_api_stream.py
```

The Python runner writes `output/evaluation.json`, including individual failures,
duration, corpus version and an explicit `semantic_accuracy: not_measured` marker.
Fixtures exercise Office reopening and protected structure, repeated-cell IDs,
Word fields/links, source-review exhaustion, targeted repair, job recovery,
cancellation, authentication and credential isolation.

Live bilingual accuracy, real-document rendered fidelity, browser behavior and
cost/latency improvements have not been established by these offline tests. The
corpus lists the real-world cases needed for that evaluation. Add approved real
source/reference pairs and compare both the previous baseline and this pipeline
before assigning a production quality score.

See [the operations guide](../operations/translation-pipeline.md) for configuration, API
contracts, persistence requirements, recovery and quality-report semantics.
