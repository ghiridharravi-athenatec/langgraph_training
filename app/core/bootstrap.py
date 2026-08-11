from app.core import config
from app.core.logger import get_logger
from app.core.security import hash_password
from app.utils.mongo import ROLE_ADMIN, create_user, ensure_indexes, get_user_by_email, upsert_default_project

logger = get_logger(__name__)

DEFAULT_PROJECT_ID = "ragchatbot"
DEFAULT_PROJECT_NAME = "RAG Chatbot"
DEFAULT_PROJECT_DESCRIPTION = "Retrieval Augmented Generation chatbot over warranty, user manual and inspection report documents."


def seed_defaults() -> None:
    ensure_indexes()

    upsert_default_project(DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NAME, DEFAULT_PROJECT_DESCRIPTION)
    logger.info("Ensured default project '%s' exists", DEFAULT_PROJECT_ID)

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
