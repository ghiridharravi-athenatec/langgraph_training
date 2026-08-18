from fastapi import APIRouter, Depends

from app.core import progress
from app.core.security import get_current_user

# Auth-gated (any logged-in user) but not project-scoped - request_id is a
# client-generated UUID (unguessable), and the value returned is always just a
# cosmetic "what's happening right now" label, never anything sensitive - see
# app/core/progress.py.
router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("/{request_id}")
def get_progress(request_id: str, current_user: dict = Depends(get_current_user)):
    return {"stage": progress.get(request_id)}
