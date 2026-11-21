from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{8,15}$")


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class OtpRequestIn(BaseModel):
    phone: str = Field(pattern=r"^\+?[0-9]{8,15}$")


class OtpVerifyIn(OtpRequestIn):
    code: str = Field(min_length=6, max_length=6)


class UserOut(ORM):
    id: int
    player_code: str
    name: str
    email: str
    phone: str | None
    phone_verified: bool
    avatar_url: str | None
    status: str


class MeOut(UserOut):
    roles: list[str]


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = None


class RoleIn(BaseModel):
    role: str = Field(pattern=r"^(super_admin|tournament_admin|umpire|captain|player)$")
    season_id: int | None = None


class StatusIn(BaseModel):
    status: str = Field(pattern=r"^(active|suspended|banned)$")


class SeasonIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    status: str = Field(default="draft", pattern=r"^(draft|active|completed|archived)$")
    starts_on: datetime | None = None
    ends_on: datetime | None = None


class SeasonPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    status: str | None = Field(default=None, pattern=r"^(draft|active|completed|archived)$")
    starts_on: datetime | None = None
    ends_on: datetime | None = None


class SeasonOut(ORM):
    id: int
    name: str
    status: str
    starts_on: datetime | None
    ends_on: datetime | None
    rule_set_id: int | None


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    logo_url: str | None = None
    color: str | None = Field(default=None, max_length=16)


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    logo_url: str | None = None
    color: str | None = Field(default=None, max_length=16)
    captain_id: int | None = None
    vice_captain_id: int | None = None


class TeamOut(ORM):
    id: int
    season_id: int
    name: str
    logo_url: str | None
    color: str | None
    captain_id: int | None
    vice_captain_id: int | None


class MemberIn(BaseModel):
    user_id: int | None = None  # omitted = request to join as self


class MemberOut(ORM):
    user_id: int
    status: str
    name: str | None = None
    player_code: str | None = None


class TeamDetail(TeamOut):
    members: list[MemberOut]


class MatchIn(BaseModel):
    team_a_id: int
    team_b_id: int
    umpire_id: int | None = None
    scheduled_at: datetime | None = None


class MatchPatch(BaseModel):
    umpire_id: int | None = None
    scheduled_at: datetime | None = None


class MatchOut(ORM):
    id: int
    season_id: int
    match_no: int
    team_a_id: int
    team_b_id: int
    umpire_id: int | None
    scheduled_at: datetime | None
    status: str


class LineupIn(BaseModel):
    team_id: int
    user_ids: list[int]


class LineupPlayer(ORM):
    team_id: int
    user_id: int
    batting_order: int | None


class MatchDetail(MatchOut):
    lineup: list[LineupPlayer]
