from pathlib import Path

CRON_TEMPLATE = Path("ops/market-regime-loader.cron")
QUALITY_GATES_WORKFLOW = Path(".github/workflows/quality-gates.yml")


def _job_line() -> str:
    return next(
        line
        for line in CRON_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )


def test_saturday_daily_update_cron_template_is_operational() -> None:
    job = _job_line()

    assert job.startswith("0 10 * * 6 ")
    assert "--lake-root /srv/market-regime/lake run-daily" in job
    assert ">> /var/log/market-regime-loader.log 2>&1" in job


def test_cron_template_has_exactly_one_job() -> None:
    jobs = [
        line
        for line in CRON_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    assert jobs == [_job_line()]


def test_ingestion_is_not_scheduled_in_github_actions() -> None:
    assert "schedule:" not in QUALITY_GATES_WORKFLOW.read_text(encoding="utf-8")
