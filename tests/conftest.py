"""Keep the tests independent of a developer's .env (loaded when app.config is imported)."""

import pytest

DEPLOY_SETTINGS = ("PHILOCAFE_ACCESS_CODE", "PHILOCAFE_CHECKPOINT_URL", "DATABASE_URL", "POSTGRES_URL",
                   "CRON_SECRET", "PHILOCAFE_RETENTION_HOURS", "PHILOCAFE_FAKE", "VERCEL", "PHILOCAFE_SECRET",
                   "PHILOCAFE_VOICE_PROVIDER")


@pytest.fixture(autouse=True)
def no_deploy_settings(monkeypatch):
    for name in DEPLOY_SETTINGS:
        monkeypatch.delenv(name, raising=False)
