"""Create or promote a super admin. Run: python -m app.create_admin EMAIL PASSWORD "Name" """

import asyncio
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import User, UserRole
from app.db.session import SessionLocal


async def main(email: str, password: str, name: str) -> None:
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == email.lower()))
        if not user:
            user = User(
                player_code="tmp", name=name, email=email.lower(), password_hash=hash_password(password)
            )
            s.add(user)
            await s.flush()
            user.player_code = f"FFP{user.id:05d}"
        has = await s.scalar(
            select(UserRole.id).where(UserRole.user_id == user.id, UserRole.role == "super_admin")
        )
        if not has:
            s.add(UserRole(user_id=user.id, role="super_admin"))
        await s.commit()
        print(f"super admin ready: {user.email} ({user.player_code})")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit('usage: python -m app.create_admin EMAIL PASSWORD "Name"')
    asyncio.run(main(*sys.argv[1:4]))
