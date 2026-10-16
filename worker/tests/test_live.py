"""Smoke tests against the real ATS endpoints. Run with ``uv run pytest -m live``.

Postings rot; when one of these flips, re-check it at the ATS and update the id.
Known states as of 2026-10-15.
"""

import pytest

from job_radar.adapters import (
    AshbyAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    RecruiteeAdapter,
    WorkableAdapter,
)

pytestmark = pytest.mark.live


def test_ashby_open():
    # Sticker Mule "Software engineer" (evergreen posting).
    assert AshbyAdapter().is_open("stickermule", "6db27241-e2d4-4f35-a2c4-b58d84621843")


def test_ashby_closed():
    # Supabase Frontend Engineer, closed 2026-10-14.
    assert not AshbyAdapter().is_open("supabase", "f048dd68-63f8-4f98-9860-3d5a43c09a01")


def test_greenhouse_board_lists_jobs():
    assert len(GreenhouseAdapter().list("binance")) > 0


def test_lever_board_lists_jobs():
    assert len(LeverAdapter().list("binance")) > 0


def test_recruitee_board_lists_jobs():
    assert len(RecruiteeAdapter().list("bunq")) > 0


def test_workable_board_lists_jobs():
    assert len(WorkableAdapter().list("seeq")) > 0
