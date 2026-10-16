from datetime import timedelta

import pytest

from job_radar import digest
from job_radar.eligibility import Candidate
from job_radar.store import Store

from .test_pipeline import T0, posting

ENV = {"SMTP_HOST": "smtp.test", "DIGEST_FROM": "radar@test", "DIGEST_TO": "me@test"}


def store_with(postings, when=T0) -> Store:
    store = Store()
    cid, _ = store.add_company("Acme", "lever", "acme", now=when)
    store.sync_board(cid, postings, when)
    return store


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        FakeSMTP.sent.append(message)


def test_select_keeps_new_eligible_postings_in_followed_domains():
    store = store_with(
        [
            posting("eng", "Frontend Engineer"),
            posting("mkt", "Growth Marketing Manager"),
            posting("us", "Backend Engineer"),
        ]
    )
    store.db.execute("UPDATE postings SET location = 'Remote (USA)' WHERE ats_job_id = 'us'")
    store.db.execute("UPDATE postings SET location = 'Remote - Worldwide' WHERE ats_job_id != 'us'")
    items, total = digest.select(
        store,
        candidate=Candidate(),
        since=T0 - timedelta(hours=1),
        categories={"engineering"},
    )
    assert [i.title for i in items] == ["Frontend Engineer"]
    assert total == 1


def test_run_sends_once_and_next_digest_only_has_newer_postings():
    FakeSMTP.sent = []
    store = store_with([posting("a", "Frontend Engineer")])
    store.db.execute("UPDATE postings SET location = 'Anywhere'")
    result = digest.run(
        store,
        candidate=Candidate(),
        categories=None,
        now=T0 + timedelta(hours=1),
        env=ENV,
        deliver=True,
        smtp=FakeSMTP,
    )
    assert result["total"] == 1
    assert FakeSMTP.sent[0]["To"] == "me@test"
    assert "Frontend Engineer" in FakeSMTP.sent[0].get_body(("plain",)).get_content()

    again = digest.run(
        store,
        candidate=Candidate(),
        categories=None,
        now=T0 + timedelta(days=1),
        env=ENV,
        deliver=False,
        smtp=FakeSMTP,
    )
    assert again["total"] == 0
    assert "沒有新的可申請職缺" in again["subject"]


def test_send_refuses_without_config_and_records_nothing():
    store = store_with([])
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        digest.run(
            store,
            candidate=Candidate(),
            categories=None,
            now=T0,
            env={},
            deliver=True,
            smtp=FakeSMTP,
        )
    assert digest.last_digest_at(store) is None


def test_render_escapes_html():
    item = digest.DigestItem("A&B", "<Lead>", "工程", None, "https://x.test/?a=1&b=2", "不限地區")
    _, text, body = digest.render([item], 1, T0)
    assert "<Lead>" in text
    assert "&lt;Lead&gt;" in body and "a=1&amp;b=2" in body
