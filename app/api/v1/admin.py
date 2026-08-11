from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.core.logger import get_logger
from app.core.security import require_admin
from app.schemas.project_schema import AdminUserOut, PermissionsUpdate, ProjectCreate, ProjectOut
from app.utils.mongo import (
    create_project,
    get_user_by_id,
    list_all_permissions,
    list_projects,
    list_users,
    set_user_permissions,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
logger = get_logger(__name__)


@router.get("/users", response_model=list[AdminUserOut])
def get_all_users():
    permissions_by_user = list_all_permissions()
    return [
        AdminUserOut(
            id=user["_id"],
            email=user["email"],
            role=user["role"],
            projects=permissions_by_user.get(user["_id"], []),
        )
        for user in list_users()
    ]


@router.get("/projects", response_model=list[ProjectOut])
def get_all_projects():
    return [
        ProjectOut(id=p["_id"], name=p["name"], description=p.get("description", ""), enabled=p.get("enabled", True))
        for p in list_projects()
    ]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def register_project(payload: ProjectCreate):
    try:
        project = create_project(payload.id, payload.name, payload.description, payload.enabled)
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Project '{payload.id}' already exists")

    logger.info("Admin registered new project '%s'", project["_id"])
    return ProjectOut(id=project["_id"], name=project["name"], description=project["description"], enabled=project["enabled"])


@router.get("/users/{user_id}/permissions", response_model=list[str])
def get_user_permissions(user_id: str):
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return list_all_permissions().get(user_id, [])


@router.put("/users/{user_id}/permissions", response_model=list[str])
def update_user_permissions(user_id: str, payload: PermissionsUpdate):
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    known_project_ids = {p["_id"] for p in list_projects()}
    unknown = set(payload.projects) - known_project_ids
    if unknown:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown project id(s): {', '.join(sorted(unknown))}")

    set_user_permissions(user_id, payload.projects)
    logger.info("Admin updated permissions for %s -> %s", user["email"], payload.projects)
    return payload.projects
