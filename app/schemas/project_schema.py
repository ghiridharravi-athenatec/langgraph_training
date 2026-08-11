import re
from typing import List

from pydantic import BaseModel, field_validator

_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: bool = True


class ProjectCreate(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def id_must_be_slug(cls, v: str) -> str:
        if not _PROJECT_ID_RE.match(v):
            raise ValueError(
                "Project id must be lowercase alphanumeric with hyphens only, 2-64 chars (e.g. 'document-search')"
            )
        return v

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class PermissionsUpdate(BaseModel):
    projects: List[str]


class UserPermissions(BaseModel):
    user_id: str
    email: str
    role: str
    projects: List[ProjectOut]


class AdminUserOut(BaseModel):
    id: str
    email: str
    role: str
    projects: List[str]
