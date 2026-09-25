"""Serializable contracts shared by adapters, specialists and job workers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import hashlib


def stable_id(part: str, location: str) -> str:
    return hashlib.sha256(f"{part}\0{location}".encode()).hexdigest()[:24]


@dataclass
class Segment:
    id: str
    source: str
    part: str
    location: str
    context: str = ""
    protected: dict[str, Any] = field(default_factory=dict)
    category: str = "text"


@dataclass
class Finding:
    code: str
    message: str
    severity: str = "review"
    segment_id: str | None = None
    location: str | None = None


@dataclass
class Manifest:
    kind: str
    sha256: str
    segments: list[Segment] = field(default_factory=list)
    assets: dict[str, str] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Plan:
    tools: list[str]
    reason: str
    confidence: float = 1.0
    max_repairs: int = 2
    max_model_calls: int = 48
    acceptance: list[str] = field(default_factory=lambda: [
        "complete_segment_coverage", "immutable_structure", "source_grounded_review", "visual_review"])


@dataclass
class QualityReport:
    status: str = "needs_review"
    checks: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    plan: Plan | None = None
    manifest: Manifest | None = None
    model_calls: int = 0
    repairs: int = 0
    observed_failure_codes: list[str] = field(default_factory=list)

    def finish(self) -> "QualityReport":
        if any(f.severity == "error" for f in self.findings) or "failed" in self.checks.values():
            self.status = "failed"
        elif any(f.severity == "review" for f in self.findings) or any(
                value != "passed" for value in self.checks.values()) or not self.checks:
            self.status = "needs_review"
        else:
            self.status = "passed"
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.finish())


class QualityFailure(ValueError):
    """An artifact cannot be delivered because a hard invariant failed."""
    def __init__(self, report: QualityReport):
        self.report = report.finish()
        failed = [name.replace('_', ' ') for name, status in self.report.checks.items() if status == 'failed']
        message = 'Document blocked by quality checks'
        if failed:
            message += ': ' + ', '.join(failed)
        message += '. See the quality report.'
        if any(f.code == 'provider_unavailable' for f in self.report.findings):
            message += (' The translation provider was unavailable after retries. Saved translations are retained; '
                        'check connectivity and choose Resume failed/cancelled files.')
        super().__init__(message)
