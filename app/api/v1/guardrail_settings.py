from fastapi import APIRouter, Depends

from app.core import guardrail_config
from app.core.logger import get_logger
from app.core.security import require_admin, require_project_access
from app.schemas.guardrail_config_schema import GuardrailConfigOut, GuardrailConfigUpdate

logger = get_logger(__name__)

# Viewing today's values sits behind the same "guardrail-traces" project grant as the
# rest of the observability surface. Changing them is a stricter, admin-only action -
# holding that grant (e.g. to read guardrail activity) must never be enough to
# let someone loosen quota, PII detection, or safety thresholds for every user.
_require_traces_access = require_project_access("guardrail-traces")

router = APIRouter(prefix="/traces/guardrail-config", tags=["traces"])


@router.get("", response_model=GuardrailConfigOut, dependencies=[Depends(_require_traces_access)])
def get_guardrail_config():
    return guardrail_config.get_config()


@router.put("", response_model=GuardrailConfigOut, dependencies=[Depends(require_admin)])
def update_guardrail_config(payload: GuardrailConfigUpdate):
    patch = payload.as_patch()
    updated = guardrail_config.update_config(patch)
    logger.info("Guardrail config edited via UI: %s", sorted(patch.keys()))
    return updated


@router.post("/reset", response_model=GuardrailConfigOut, dependencies=[Depends(require_admin)])
def reset_guardrail_config():
    return guardrail_config.reset_to_defaults()
