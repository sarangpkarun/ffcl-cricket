import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import otp
from app.core.config import settings
from app.core.security import (
    create_access_token,
    hash_password,
    hash_password_async,
    new_refresh_token,
    sha256,
    verify_password_async,
)
from app.db.models import OtpCode, Session, User, UserRole
from app.db.session import get_session
from app.deps import get_current_user, user_roles
from app.schemas import (
    LoginIn,
    MeOut,
    OtpRequestIn,
    OtpVerifyIn,
    ProfileIn,
    RefreshIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from app.services.ratelimit import allow

router = APIRouter(tags=["auth"])

# Hashing a throwaway password for unknown emails makes a failed login take as long as a wrong
# password for a real account, so response time does not reveal who has an account.
_DUMMY_HASH = hash_password("not-a-real-password-just-for-timing")


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def throttle(scope: str, key: str, limit: int, window_seconds: int) -> None:
    if settings.auth_rate_limits_enabled and not await allow(f"rl:auth:{scope}:{key}", limit, window_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please wait and try again.")


async def _issue(db: AsyncSession, user: User, user_agent: str | None) -> TokenOut:
    refresh = new_refresh_token()
    sess = Session(
        user_id=user.id,
        refresh_hash=sha256(refresh),
        user_agent=(user_agent or "")[:300] or None,
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_ttl_days),
    )
    db.add(sess)
    await db.commit()
    return TokenOut(access_token=create_access_token(user.id, sess.id), refresh_token=refresh)


@router.post("/auth/register", response_model=TokenOut, status_code=201)
async def register(
    body: RegisterIn,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user_agent: str | None = Header(default=None),
) -> TokenOut:
    await throttle("register-ip", client_ip(request), 10, 3600)
    user = User(
        player_code=uuid.uuid4().hex[:16],
        name=body.name,
        email=body.email.lower(),
        password_hash=await hash_password_async(body.password),
        phone=body.phone,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or phone already registered") from e
    user.player_code = f"FFP{user.id:05d}"
    db.add(UserRole(user_id=user.id, role="player"))
    return await _issue(db, user, user_agent)


@router.post("/auth/login", response_model=TokenOut)
async def login(
    body: LoginIn,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user_agent: str | None = Header(default=None),
) -> TokenOut:
    email = body.email.lower()
    await throttle("login-ip", client_ip(request), 30, 300)
    await throttle("login-email", email, 10, 300)
    user = await db.scalar(select(User).where(User.email == email))
    ok = await verify_password_async(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account {user.status}")
    return await _issue(db, user, user_agent)


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, db: AsyncSession = Depends(get_session)) -> TokenOut:
    sess = await db.scalar(select(Session).where(Session.refresh_hash == sha256(body.refresh_token)))
    if not sess or sess.revoked_at or sess.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    user = await db.get(User, sess.user_id)
    if not user or user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account not active")
    # Rotate: revoke old session, issue a new one.
    sess.revoked_at = datetime.now(UTC)
    return await _issue(db, user, sess.user_agent)


@router.post("/auth/logout", status_code=204)
async def logout(
    body: RefreshIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> None:
    await db.execute(
        update(Session)
        .where(Session.refresh_hash == sha256(body.refresh_token), Session.user_id == user.id)
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


@router.post("/auth/logout-all", status_code=204)
async def logout_all(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> None:
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


@router.post("/auth/otp/request", status_code=204)
async def otp_request(
    body: OtpRequestIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    if user.phone != body.phone:
        raise HTTPException(400, "Phone must match your registered number")
    await throttle("otp-request", str(user.id), 3, 600)  # each request may cost an SMS
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(
        OtpCode(
            phone=body.phone,
            code_hash=sha256(code),
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.otp_ttl_minutes),
        )
    )
    await db.commit()
    otp.get_provider().send(body.phone, code)


@router.post("/auth/otp/verify", status_code=204)
async def otp_verify(
    body: OtpVerifyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    if user.phone != body.phone:
        raise HTTPException(400, "Phone must match your registered number")
    rec = await db.scalar(
        select(OtpCode)
        .where(OtpCode.phone == body.phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.id.desc())
        .limit(1)
    )
    if not rec or rec.expires_at < datetime.now(UTC) or rec.attempts >= settings.otp_max_attempts:
        raise HTTPException(400, "Code expired or too many attempts")
    rec.attempts += 1
    if not secrets.compare_digest(rec.code_hash, sha256(body.code)):
        await db.commit()
        raise HTTPException(400, "Incorrect code")
    rec.consumed_at = datetime.now(UTC)
    user.phone_verified = True
    await db.commit()


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> MeOut:
    base = UserOut.model_validate(user).model_dump()
    return MeOut(**base, roles=sorted(await user_roles(db, user.id)))


@router.patch("/me", response_model=MeOut)
async def update_me(
    body: ProfileIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> MeOut:
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(user, k, v)
    await db.commit()
    return await me(user, db)
