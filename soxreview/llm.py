"""Reviewers that read free-text ticket notes and report approval evidence.

The model never decides PASS or FAIL. It extracts what the notes say (who
approved, in what role, when, and the exact sentence that shows it). The
deterministic reconciler then checks those facts against the authorised
approvers and the grant time, verifies the quote is really in the notes, and
routes the item to a human tester.

* OfflineReviewer - regex extraction for the note formats in the synthetic data.
                    Lets the whole pipeline and its tests run without an API key.
* ClaudeReviewer  - the Anthropic Messages API with a JSON schema output, so the
                    response always parses into the same fields.
"""
from __future__ import annotations

import json
import re
from typing import Protocol

from .models import LLMFinding

FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "approval_evidence_found": {"type": "boolean"},
        "approver": {"type": ["string", "null"], "description": "Pseudonym (P-XXXXXX) of the approver, exactly as written in the notes"},
        "approver_role": {"type": "string", "enum": ["manager", "group_owner", "other", "unknown"]},
        "approval_time": {"type": ["string", "null"], "description": "YYYY-MM-DD HH:MM as written in the notes, else null"},
        "quote": {"type": "string", "description": "The exact sentence from the notes that shows the approval, copied verbatim; empty if none"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {"type": "string"},
    },
    "required": ["approval_evidence_found", "approver", "approver_role", "approval_time", "quote", "confidence", "rationale"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You assist an IT auditor testing a SOX IT general control: every change that grants \
access to a financially significant system must be approved by an authorised person before the access is granted.

You receive one access change as JSON. The structured approval field on the ticket is missing or not \
"approved", so the auditor needs to know whether the free-text notes contain documented approval evidence.

Report only what the notes state. Documented approval means a written record (an e-mail, a ticket approval, \
a signed form) from a named person. A verbal approval, an assumption, or "it was fine" is not documented \
approval: set approval_evidence_found to false for those, and explain why in the rationale.

People appear as pseudonyms like P-1A2B3C. Copy the approver's pseudonym and the approval time exactly as \
they appear. Copy the quote verbatim from the notes; the auditor's tool rejects any quote that is not an \
exact substring. Do not decide whether the control passed: the tool compares your facts with the authorised \
approvers and the grant time."""


class Reviewer(Protocol):
    name: str

    def review(self, payload: dict) -> LLMFinding: ...


class OfflineReviewer:
    """Deterministic stand-in for the model, for CI and for running without an API key."""

    name = "offline-rules"
    _approved = re.compile(
        r"(?P<sentence>[^.]*?(?P<who>P-[0-9A-F]{6}) \((?P<role>manager|group owner|owner)\) approved by "
        r"(?P<medium>email|e-mail|ticket)[^.]*?on (?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2})[^.]*)")
    _verbal = re.compile(r"(said|verbal|on a call|no written approval)", re.I)

    def review(self, payload: dict) -> LLMFinding:
        notes = payload.get("notes", "")
        m = self._approved.search(notes)
        if m:
            role = "group_owner" if "owner" in m.group("role") else "manager"
            return LLMFinding(True, m.group("who"), role, m.group("ts"), m.group("sentence").strip(),
                              "high", f"Notes record a written {m.group('medium')} approval.", self.name)
        if self._verbal.search(notes):
            return LLMFinding(False, None, "unknown", None, "", "high",
                              "Notes describe a verbal or informal approval only; no written record.", self.name)
        return LLMFinding(False, None, "unknown", None, "", "medium", "No approval is mentioned in the notes.", self.name)


class ClaudeReviewer:
    """Claude via the Anthropic Python SDK (pip install anthropic).

    Credentials resolve the standard SDK way (ANTHROPIC_API_KEY, or an `ant auth login` profile).
    Server-side refusal fallbacks are enabled so a safety decline is retried on a
    fallback model inside the same call instead of failing the item.
    """

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", client=None):
        import anthropic  # optional dependency, imported only when this reviewer is used

        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.name = model

    def review(self, payload: dict) -> LLMFinding:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": FINDING_SCHEMA},
            },
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
        if response.stop_reason == "refusal":
            return LLMFinding(False, None, "unknown", None, "", "low",
                              "Model declined to review this item; routed to manual review.", self.name)
        if response.stop_reason == "max_tokens":
            return LLMFinding(False, None, "unknown", None, "", "low",
                              "Model output was cut off; routed to manual review.", self.name)
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
        return LLMFinding(reviewer=response.model, **data)


def make_reviewer(kind: str, model: str = "claude-opus-5-5") -> Reviewer:
    if kind == "offline":
        return OfflineReviewer()
    if kind == "claude":
        return ClaudeReviewer(model=model)
    raise ValueError(f"unknown reviewer {kind!r} (use offline or claude)")
