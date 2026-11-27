"""Load the monthly evidence population.

Two sources share one shape (list of dicts keyed by column name):

* CsvSource         - exports saved from ServiceNow and the directory audit log
* ServiceNowSource  - read-only pulls from the ServiceNow Table API, with a
                      completeness check against the Aggregate API count

Every file read is hashed (SHA-256) so the evidence pack can prove which exact
inputs produced the results.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

TABLES = ("users", "groups", "access_events", "ritms", "incidents")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Population:
    users: list[dict]
    groups: list[dict]
    access_events: list[dict]
    ritms: list[dict]
    incidents: list[dict]
    checksums: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def users_by_id(self) -> dict[str, dict]:
        return {u["user_id"]: u for u in self.users}

    @property
    def groups_by_id(self) -> dict[str, dict]:
        return {g["group_id"]: g for g in self.groups}

    @property
    def ritms_by_number(self) -> dict[str, dict]:
        return {r["number"]: r for r in self.ritms}

    @property
    def incidents_by_number(self) -> dict[str, dict]:
        return {i["number"]: i for i in self.incidents}


class CsvSource:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def load(self) -> Population:
        data, sums = {}, {}
        for t in TABLES:
            path = self.folder / f"{t}.csv"
            with path.open(newline="") as fh:
                data[t] = list(csv.DictReader(fh))
            sums[path.name] = sha256_file(path)
        return Population(**data, checksums=sums)


class ServiceNowSource:
    """Read-only ServiceNow pulls. Only GET requests are ever issued.

    Authentication is an OAuth bearer token from the SN_TOKEN environment
    variable (an integration user limited to read roles on the tables used).
    The directory tables (users, groups, access events) still come from CSV
    exports of the identity platform's audit log.
    """

    RITM_FIELDS = ["number", "cat_item.name", "opened_at", "requested_by", "request.requested_for",
                   "u_group", "approval", "u_approver", "u_approved_at", "u_fulfilled_by", "closed_at",
                   "state", "work_notes"]

    def __init__(self, instance: str, directory_csv: Path, period: str,
                 token: str | None = None, opener: Callable | None = None, page_size: int = 500):
        self.base = f"https://{instance}.service-now.com"
        self.token = token or os.environ.get("SN_TOKEN", "")
        self.directory_csv = Path(directory_csv)
        self.period = period
        self.page_size = page_size
        self._open = opener or urllib.request.urlopen

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, method="GET", headers={
            "Accept": "application/json", "Authorization": f"Bearer {self.token}"})
        with self._open(req) as resp:
            return json.loads(resp.read().decode())

    def _period_query(self, field_name: str) -> str:
        y, m = map(int, self.period.split("-"))
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        return (f"{field_name}>=javascript:gs.dateGenerate('{y}-{m:02d}-01','00:00:00')^"
                f"{field_name}<javascript:gs.dateGenerate('{ny}-{nm:02d}-01','00:00:00')")

    def fetch_table(self, table: str, query: str, fields: list[str]) -> tuple[list[dict], int]:
        rows, offset = [], 0
        while True:
            page = self._get(f"/api/now/table/{table}", {
                "sysparm_query": query, "sysparm_fields": ",".join(fields),
                "sysparm_display_value": "true", "sysparm_exclude_reference_link": "true",
                "sysparm_limit": self.page_size, "sysparm_offset": offset})["result"]
            rows.extend(page)
            if len(page) < self.page_size:
                break
            offset += self.page_size
        stats = self._get(f"/api/now/stats/{table}", {"sysparm_query": query, "sysparm_count": "true"})
        expected = int(stats["result"]["stats"]["count"])
        return rows, expected

    def load(self) -> Population:
        base = CsvSource(self.directory_csv).load()
        warnings = []
        ritms, expected = self.fetch_table("sc_req_item", self._period_query("closed_at"), self.RITM_FIELDS)
        if len(ritms) != expected:
            # The Aggregate API counts rows the integration user cannot read; the Table
            # API silently drops them. A gap usually means row-level ACLs, not lost data.
            warnings.append(f"sc_req_item: Table API returned {len(ritms)} rows but Aggregate API counts {expected}. "
                            "Check row-level ACLs for the integration user before relying on this population.")
        base.ritms = [self._map_ritm(r) for r in ritms]
        raw = json.dumps(ritms, sort_keys=True).encode()
        base.checksums["servicenow:sc_req_item"] = hashlib.sha256(raw).hexdigest()
        base.warnings.extend(warnings)
        return base

    @staticmethod
    def _map_ritm(r: dict) -> dict:
        return {"number": r.get("number", ""), "catalog_item": r.get("cat_item.name", ""),
                "opened_at": r.get("opened_at", ""), "requested_by": r.get("requested_by", ""),
                "requested_for": r.get("request.requested_for", ""), "group_id": r.get("u_group", ""),
                "approval": (r.get("approval") or "").lower(), "approver_id": r.get("u_approver", ""),
                "approved_at": r.get("u_approved_at", ""), "fulfilled_by": r.get("u_fulfilled_by", ""),
                "closed_at": r.get("closed_at", ""), "state": r.get("state", ""),
                "work_notes": r.get("work_notes", "")}
