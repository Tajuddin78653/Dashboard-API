import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.database import AsyncSessionLocal
from app.models.user import User


async def seed():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == "admin@tradedash.com"))
        if result.scalar_one_or_none():
            print("Admin already exists")
            return

        admin = User(
            email="admin@tradedash.com",
            hashed_password=hash_password("TradeDash@2025"),
            name="Admin",
            role="admin",
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        print("Admin user created: admin@tradedash.com / TradeDash@2025")


if __name__ == "__main__":
    asyncio.run(seed())
