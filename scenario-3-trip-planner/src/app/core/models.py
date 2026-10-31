from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TravelerProfile(BaseModel):
    traveller_id: str = "TRV-GUEST"
    adults: int | None = None
    children_count: int = 0
    children_ages: list[int] = Field(default_factory=list)
    party_note: str | None = None
    budget: float | None = None
    currency: str = "USD"
    destination: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    interests: list[str] = Field(default_factory=list)
    lodging_style: str | None = None
    walking_style: str | None = None
    origin: str | None = None
    gift_heavy: bool = False
    passport_nationality: str | None = None
    style_asked: bool = False
    hotel_stars: int | None = None
    hotel_board: str | None = None
    hotel_budget: float | None = None
    hotel_area: str | None = None
    flight_bags: int | None = None
    flight_bag_kg: float | None = None
    flight_time_pref: str | None = None


class SessionState(BaseModel):
    session_id: str
    profile: TravelerProfile = Field(default_factory=TravelerProfile)
    history: list[dict[str, str]] = Field(default_factory=list)
    itinerary: dict[str, Any] | None = None
    pending_action: dict[str, Any] | None = None
    last_sources: list[dict[str, Any]] = Field(default_factory=list)
    last_agents: list[dict[str, Any]] = Field(default_factory=list)
    completed_actions: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    user: dict[str, Any] | None = None


class ApproveRequest(BaseModel):
    session_id: str
    action_id: str
    approved: bool
