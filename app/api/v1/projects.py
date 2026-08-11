from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.schemas.project_schema import ProjectOut
from app.utils.mongo import ROLE_ADMIN, list_permitted_project_ids, list_projects

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def get_visible_projects(current_user: dict = Depends(get_current_user)):
    '''Drives the "My Projects" dashboard - admins see every enabled project,
    regular users see only the enabled projects they've been explicitly granted.'''
    enabled_projects = list_projects(only_enabled=True)

    if current_user.get("role") == ROLE_ADMIN:
        visible = enabled_projects
    else:
        permitted_ids = set(list_permitted_project_ids(current_user["_id"]))
        visible = [p for p in enabled_projects if p["_id"] in permitted_ids]

    return [
        ProjectOut(id=p["_id"], name=p["name"], description=p.get("description", ""), enabled=p.get("enabled", True))
        for p in visible
    ]
