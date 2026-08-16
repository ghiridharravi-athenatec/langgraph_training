'''REQUIRE_PERSISTENT_ENCRYPTION_KEYS (app/core/config.py) is an opt-in flag that
turns the PII/DB-credential encryption keys' normal "warn and fall back to an
ephemeral key" behavior into a hard failure - so a production deployment can ask
to fail fast at startup instead of silently generating unrecoverable data. Off by
default, so every other test in the suite runs against the default (permissive)
behavior without needing either key configured.

Calls _build_fernet() directly (rather than reloading either module) so these
tests can't leave app.core.guardrails/db_connections' shared `_fernet` global
mutated for the rest of the pytest session.
'''

import pytest

from app.core import db_connections, guardrails


def test_guardrails_falls_back_to_ephemeral_key_by_default(monkeypatch):
    monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(guardrails.config, "REQUIRE_PERSISTENT_ENCRYPTION_KEYS", False)
    assert guardrails._build_fernet() is not None  # does not raise


def test_guardrails_raises_when_key_unset_and_flag_is_set(monkeypatch):
    monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(guardrails.config, "REQUIRE_PERSISTENT_ENCRYPTION_KEYS", True)
    with pytest.raises(RuntimeError, match="PII_ENCRYPTION_KEY"):
        guardrails._build_fernet()


def test_guardrails_raises_when_key_malformed_and_flag_is_set(monkeypatch):
    monkeypatch.setenv("PII_ENCRYPTION_KEY", "not-a-real-key")
    monkeypatch.setattr(guardrails.config, "REQUIRE_PERSISTENT_ENCRYPTION_KEYS", True)
    with pytest.raises(RuntimeError, match="PII_ENCRYPTION_KEY"):
        guardrails._build_fernet()


def test_db_connections_falls_back_to_ephemeral_key_by_default(monkeypatch):
    monkeypatch.setattr(db_connections.config, "DB_CREDENTIAL_ENCRYPTION_KEY", "")
    monkeypatch.setattr(db_connections.config, "REQUIRE_PERSISTENT_ENCRYPTION_KEYS", False)
    assert db_connections._build_fernet() is not None  # does not raise


def test_db_connections_raises_when_key_unset_and_flag_is_set(monkeypatch):
    monkeypatch.setattr(db_connections.config, "DB_CREDENTIAL_ENCRYPTION_KEY", "")
    monkeypatch.setattr(db_connections.config, "REQUIRE_PERSISTENT_ENCRYPTION_KEYS", True)
    with pytest.raises(RuntimeError, match="DB_CREDENTIAL_ENCRYPTION_KEY"):
        db_connections._build_fernet()


def test_db_connections_raises_when_key_malformed_and_flag_is_set(monkeypatch):
    monkeypatch.setattr(db_connections.config, "DB_CREDENTIAL_ENCRYPTION_KEY", "not-a-real-key")
    monkeypatch.setattr(db_connections.config, "REQUIRE_PERSISTENT_ENCRYPTION_KEYS", True)
    with pytest.raises(RuntimeError, match="DB_CREDENTIAL_ENCRYPTION_KEY"):
        db_connections._build_fernet()
