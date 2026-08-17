from app.core import config, guardrail_config
from app.core import guardrails
from app.core.logger import get_logger
from app.core.security import hash_password
from app.utils.mongo import (
    ROLE_ADMIN,
    backfill_conversation_project_ids,
    create_user,
    ensure_indexes,
    get_user_by_email,
    rename_project_if_still_default,
    upsert_default_project,
)

_OLD_DEFAULT_PROJECT_NAME = "Conversational Assistant"

logger = get_logger(__name__)

DEFAULT_PROJECT_ID = "ragchatbot"
DEFAULT_PROJECT_NAME = "Document Chatbot"
DEFAULT_PROJECT_DESCRIPTION = "Chat over whatever documents your team has uploaded."

DATABASE_PROJECT_ID = "database-chatbot"
DATABASE_PROJECT_NAME = "Database Chatbot"
DATABASE_PROJECT_DESCRIPTION = "Chat with a connected external database - read-only, powered by an agentic tool-calling loop."

TRACES_PROJECT_ID = "guardrail-traces"
TRACES_PROJECT_NAME = "Guardrails Observability"
TRACES_PROJECT_DESCRIPTION = "Guardrail observability across every user's conversations - who asked what, and every check it passed through."


def seed_defaults() -> None:
    ensure_indexes()

    upsert_default_project(DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NAME, DEFAULT_PROJECT_DESCRIPTION)
    logger.info("Ensured default project '%s' exists", DEFAULT_PROJECT_ID)
    if rename_project_if_still_default(
        DEFAULT_PROJECT_ID, _OLD_DEFAULT_PROJECT_NAME, DEFAULT_PROJECT_NAME, DEFAULT_PROJECT_DESCRIPTION,
    ):
        logger.info("Renamed project '%s' to '%s'", DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NAME)

    upsert_default_project(DATABASE_PROJECT_ID, DATABASE_PROJECT_NAME, DATABASE_PROJECT_DESCRIPTION)
    logger.info("Ensured default project '%s' exists", DATABASE_PROJECT_ID)

    upsert_default_project(TRACES_PROJECT_ID, TRACES_PROJECT_NAME, TRACES_PROJECT_DESCRIPTION)
    logger.info("Ensured default project '%s' exists", TRACES_PROJECT_ID)

    # One-time migration: conversations created before project-scoping existed have no
    # project_id - they can only have come from the document chatbot (the only chat
    # surface that existed then), so backfill them there instead of letting them
    # silently vanish from every project's scoped conversation list.
    backfilled = backfill_conversation_project_ids(DEFAULT_PROJECT_ID)
    if backfilled:
        logger.info("Backfilled project_id='%s' onto %d pre-existing conversation(s)", DEFAULT_PROJECT_ID, backfilled)

    guardrail_config.refresh_from_mongo()

    guardrails.warm_up()
    logger.info("Warmed up the PII analyzer (spaCy model loaded)")

    if not config.ADMIN_EMAIL or not config.ADMIN_PASSWORD:
        logger.warning(
            "ADMIN_EMAIL/ADMIN_PASSWORD not set - skipping admin bootstrap. "
            "Set both in your environment and restart to create the initial admin user."
        )
        return

    if get_user_by_email(config.ADMIN_EMAIL) is not None:
        logger.info("Admin user '%s' already exists, skipping creation", config.ADMIN_EMAIL)
        return

    create_user(config.ADMIN_EMAIL, hash_password(config.ADMIN_PASSWORD), role=ROLE_ADMIN)
    logger.info("Created initial admin user '%s'", config.ADMIN_EMAIL)
