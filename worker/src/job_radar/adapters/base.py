"""Common types for ATS source adapters.

Every adapter implements the same three calls (see docs/spec.md, 資料來源與 ATS 整合):

- ``list(org)``      -> all open postings on the company's board
- ``get(org, id)``   -> one posting, or ``None`` when the ATS says it is gone
- ``is_open(org, id)``

The ATS is the source of truth for "is this posting still open"; aggregators are
only used to discover companies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

USER_AGENT = "job-radar/0.1"
DEFAULT_TIMEOUT = httpx.Timeout(20.0)


@dataclass(slots=True)
class Posting:
    ats: str
    org: str
    ats_job_id: str
    title: str
    url: str
    location: str | None = None
    is_remote: bool | None = None
    published_at: datetime | None = None
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class AdapterError(RuntimeError):
    """The ATS answered in a way we could not interpret (not the same as "closed")."""


class Adapter(ABC):
    name: str

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT, follow_redirects=True
        )

    @abstractmethod
    def list(self, org: str) -> list[Posting]: ...

    @abstractmethod
    def get(self, org: str, job_id: str) -> Posting | None: ...

    def is_open(self, org: str, job_id: str) -> bool:
        return self.get(org, job_id) is not None

    def _get_json(self, url: str, **kwargs: Any) -> Any | None:
        """GET a JSON document; ``None`` on 404, ``AdapterError`` on anything else unexpected."""
        resp = self._client.get(url, **kwargs)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise AdapterError(f"{self.name}: GET {url} -> HTTP {resp.status_code}")
        return resp.json()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
