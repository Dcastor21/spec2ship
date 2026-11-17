"""Request and response models. `XCreate` is what a client sends; `X` is what it gets back."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AwareDatetime, BaseModel, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GuardCreate(BaseModel):
    name: Text
    badge_number: Text
    license_expires_on: date


class Guard(GuardCreate):
    id: int
    active: bool


class SiteCreate(BaseModel):
    name: Text
    address: Text


class Site(SiteCreate):
    id: int


class PostCreate(BaseModel):
    name: Text


class Post(PostCreate):
    id: int
    site_id: int


class CheckpointCreate(BaseModel):
    name: Text
    tag_code: Text


class Checkpoint(CheckpointCreate):
    id: int
    site_id: int


class ShiftCreate(BaseModel):
    guard_id: int
    post_id: int
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def ends_after_start(self) -> Self:
        # Compare at the stored (whole-second) precision, so a stored shift always
        # has starts_at < ends_at.
        if self.ends_at.replace(microsecond=0) <= self.starts_at.replace(microsecond=0):
            raise ValueError("ends_at must be after starts_at")
        return self


class Shift(ShiftCreate):
    id: int


class TourCreate(BaseModel):
    site_id: int
    guard_id: int
    started_at: AwareDatetime


class ScanCreate(BaseModel):
    tag_code: Text
    scanned_at: AwareDatetime


class ScanEvent(BaseModel):
    id: int
    tour_id: int
    checkpoint_id: int
    scanned_at: AwareDatetime


class Tour(TourCreate):
    id: int
    scans: list[ScanEvent]


class IncidentCreate(BaseModel):
    site_id: int
    guard_id: int
    severity: Severity
    summary: LongText
    occurred_at: AwareDatetime


class Incident(IncidentCreate):
    id: int
