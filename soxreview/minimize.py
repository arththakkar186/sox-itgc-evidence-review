"""Data minimisation before anything is sent to a language model.

Rules:
1. Field allow-list: only the fields the question needs are included.
2. People become stable pseudonyms (P-xxxxxx, salted SHA-256), so the model can
   compare "who approved" with "who is authorised" without seeing a name.
3. Free text is scrubbed: known names -> pseudonyms, then e-mail addresses,
   phone numbers, IP addresses and URLs -> typed placeholders.
4. Roles ("manager of the user", "group owner") are worked out locally and sent
   instead of org-chart data.
"""
from __future__ import annotations

import hashlib
import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL = re.compile(r"https?://\S+")


class Pseudonymizer:
    def __init__(self, salt: str, users_by_id: dict[str, dict]):
        self.salt = salt
        self.users = users_by_id
        # Longest names first so "Avery Abbott-Lowry" is replaced before "Avery Abbott".
        self._names = sorted(((u["display_name"], uid) for uid, u in users_by_id.items()),
                             key=lambda x: -len(x[0]))
        self.redactions: dict[str, int] = {"name": 0, "email": 0, "phone": 0, "ip": 0, "url": 0}

    def pid(self, user_id: str) -> str:
        if not user_id:
            return ""
        return "P-" + hashlib.sha256(f"{self.salt}:{user_id}".encode()).hexdigest()[:6].upper()

    def scrub(self, text: str) -> str:
        if not text:
            return ""
        out = text
        for name, uid in self._names:
            if name in out:
                self.redactions["name"] += out.count(name)
                out = out.replace(name, self.pid(uid))
        for pattern, label in ((EMAIL, "email"), (URL, "url"), (IPV4, "ip"), (PHONE, "phone")):
            out, n = pattern.subn(f"[{label.upper()}]", out)
            self.redactions[label] += n
        return out


def approval_question(item_id: str, ritm: dict, event: dict, group: dict, users_by_id: dict,
                      pz: Pseudonymizer) -> dict:
    """Build the minimised payload for: 'do these notes evidence a valid approval?'."""
    target = event["target_user_id"]
    manager = users_by_id.get(target, {}).get("manager_id", "")
    return {
        "item_id": item_id,
        "ticket": ritm.get("number", ""),
        "access_granted": {"group": group["name"], "application": group["application"],
                           "to_user": pz.pid(target), "granted_at": event["timestamp"]},
        "authorized_approvers": [
            {"person": pz.pid(manager), "role": "manager"},
            {"person": pz.pid(group["owner_id"]), "role": "group_owner"},
        ],
        "structured_approval_field": ritm.get("approval", ""),
        "notes": pz.scrub(ritm.get("work_notes", "")),
    }
