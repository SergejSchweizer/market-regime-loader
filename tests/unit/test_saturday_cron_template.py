from pathlib import Path

CRON_TEMPLATE = Path("ops/market-regime-loader.cron")
QUALITY_GATES_WORKFLOW = Path(".github/workflows/quality-gates.yml")


def _job_line() -> str:
    return next(
        line
        for line in CRON_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )


def test_sunday_gold_sync_cron_template_is_operational() -> None:
    job = _job_line()

    assert job.startswith("0 10 * * 0 ")
    assert "cd /srv/market-regime-loader" in job
    assert "scripts/export_cron_config.py config.yaml" in job
    assert 'mkdir -p "$PROJECT_ROOT/.logs"' in job
    assert '--lake-root "$LAKE_ROOT" run-daily' in job
    assert '--lake-root "$LAKE_ROOT" gold-sync-postgres' in job
    assert job.index("run-daily") < job.index("gold-sync-postgres")
    assert "run-daily &&" in job
    assert '>> "$LOG_PATH" 2>&1' in job
    assert "/var/log" not in job
    assert "reconcile" not in job


def test_cron_template_has_exactly_one_job_and_no_database_secret_literal() -> None:
    text = CRON_TEMPLATE.read_text(encoding="utf-8")
    jobs = [line for line in text.splitlines() if line and not line.startswith("#")]

    assert jobs == [_job_line()]
    assert "PGPASSWORD=" not in text
    assert "postgresql://" not in text
    assert "repo-secret" not in text


def test_ingestion_is_not_scheduled_in_github_actions() -> None:
    assert "schedule:" not in QUALITY_GATES_WORKFLOW.read_text(encoding="utf-8")
