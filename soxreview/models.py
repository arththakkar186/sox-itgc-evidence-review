from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

TS_FORMAT = "%Y-%m-%d %H:%M"


def parse_ts(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in (TS_FORMAT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised timestamp {value!r}")


# Result values
PASS = "PASS"
EXCEPTION = "EXCEPTION"
NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass
class Attribute:
    """One test attribute, e.g. 'approved before provisioning'."""
    name: str
    passed: Optional[bool]          # None = could not be evaluated from structured data
    detail: str = ""


@dataclass
class LLMFinding:
    approval_evidence_found: bool
    approver: Optional[str]
    approver_role: str
    approval_time: Optional[str]
    quote: str
    confidence: str
    rationale: str
    reviewer: str                   # "offline-rules" or the Claude model id
    quote_verified: bool = False    # set locally: quote is a literal substring of the notes


@dataclass
class TestResult:
    control_id: str
    item_id: str
    attributes: list[Attribute] = field(default_factory=list)
    result: str = PASS
    recommendation: str = PASS      # what the tool proposes to the human tester
    rationale: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    llm: Optional[LLMFinding] = None

    def failed(self) -> list[Attribute]:
        return [a for a in self.attributes if a.passed is False]
