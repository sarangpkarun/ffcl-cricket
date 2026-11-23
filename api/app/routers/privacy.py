"""Delete my account, download my data."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password_async
from app.db.models import User
from app.db.session import get_session
from app.deps import get_current_user
from app.routers.auth import throttle
from app.services import privacy as svc

router = APIRouter(tags=["privacy"])


class DeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.get("/me/data")
async def my_data(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A download of everything held about the signed-in person."""
    await throttle("data-export", str(user.id), 3, 3600)
    data = await svc.export(db, user)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="ffcl-my-data-{stamp}.json"', "Cache-Control": "no-store"})


@router.get("/me/delete-check")
async def delete_check(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    """What, if anything, has to be handed over before this person can leave."""
    found = await svc.blockers(db, user)
    return {"can_delete": not found, "blockers": found}


@router.post("/me/delete", status_code=204)
async def delete_me(body: DeleteIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> None:
    await throttle("delete-account", str(user.id), 5, 3600)
    if not await verify_password_async(body.password, user.password_hash):
        raise HTTPException(403, "Wrong password")
    await svc.delete_account(db, user)
    await db.commit()
