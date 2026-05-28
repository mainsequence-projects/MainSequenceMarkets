from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IndexListRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    unique_identifier: str
    index_type: str
    display_name: str
    description: str | None = None
    provider: str | None = None


class IndexRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    unique_identifier: str
    index_type: str
    display_name: str
    description: str | None = None
    provider: str | None = None
    metadata_json: dict[str, Any] | None = None
