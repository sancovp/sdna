"""CronJob schedule-timezone tests (issue #41: cron authored in operator tz must
evaluate in that tz, not naive container-local — the 4h-early bug)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import sdna.cron as cron
from sdna.cron import CronJob, set_timezone, get_timezone, _coerce

ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _reset_tz():
    yield
    set_timezone(None)


def test_set_timezone_makes_now_aware_and_none_reverts():
    set_timezone("America/New_York")
    now = cron._now()
    assert now.tzinfo is not None
    assert get_timezone().key == "America/New_York"
    set_timezone(None)
    assert cron._now().tzinfo is None


def test_coerce_interprets_naive_stamp_as_container_local():
    set_timezone("America/New_York")
    naive_local = datetime.now()                     # how pre-fix stamps were recorded
    coerced = _coerce(naive_local)
    aware_now = datetime.now(ET)
    assert coerced.tzinfo is not None
    assert abs((aware_now - coerced).total_seconds()) < 5


def test_cron_fires_on_authoring_wall_clock_not_utc(monkeypatch):
    """'0 21 * * *' authored as 21:00 ET: at 21:00 UTC (= 17:00 ET) it must NOT
    fire (the old 4h-early bug); at 21:00 ET it must fire."""
    set_timezone("America/New_York")
    job = CronJob(name="night", schedule="0 21 * * *")
    job.last_run = datetime(2026, 7, 17, 12, 0, tzinfo=ET)

    # 21:00 UTC on the same day == 17:00 ET -> pre-fix this fired; now it must not.
    monkeypatch.setattr(cron, "_now", lambda: datetime(2026, 7, 17, 17, 0, 30, tzinfo=ET))
    assert job.is_due() is False

    # 21:00 ET (the authored wall-clock) -> fires.
    monkeypatch.setattr(cron, "_now", lambda: datetime(2026, 7, 17, 21, 0, 30, tzinfo=ET))
    assert job.is_due() is True


def test_naive_last_run_survives_tz_activation(monkeypatch):
    """A job created BEFORE set_timezone (naive last_run) must not crash or
    misfire once the tz is active — the naive stamp is coerced as local."""
    set_timezone(None)
    job = CronJob(name="mix", schedule="0 21 * * *")   # stamps naive last_run
    assert job.last_run.tzinfo is None
    set_timezone("America/New_York")
    monkeypatch.setattr(cron, "_now", lambda: datetime.now(ET))
    job.is_due()                                       # must not raise aware/naive TypeError


def test_unconfigured_behavior_unchanged():
    """No tz configured (and no env): naive local evaluation, exactly pre-fix."""
    set_timezone(None)
    job = CronJob(name="plain", schedule="*/5 * * * *")
    assert job.last_run.tzinfo is None
    assert isinstance(job.is_due(), bool)
