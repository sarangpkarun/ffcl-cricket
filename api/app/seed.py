"""Seed the default FFCL rule set. Run: python -m app.seed"""

import asyncio

from sqlalchemy import select

from app.db.models import RuleSet
from app.db.session import SessionLocal
from app.engine.rules import DEFAULT_RULES


async def main() -> None:
    async with SessionLocal() as s:
        exists = await s.scalar(select(RuleSet).where(RuleSet.name == "FFCL", RuleSet.version == 1))
        if not exists:
            s.add(RuleSet(name="FFCL", version=1, config=DEFAULT_RULES))
            await s.commit()
            print("seeded FFCL v1")
        else:
            print("already seeded")


if __name__ == "__main__":
    asyncio.run(main())
