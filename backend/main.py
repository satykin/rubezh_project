# -*- coding: utf-8 -*-
import os
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import BigInteger, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL")
HAS_DB = True

# Если базы нет, уходим в безопасный холостой режим
if not DATABASE_URL:
    print("WARNING: DATABASE_URL environment variable is empty. Running in dry mode.")
    DATABASE_URL = "postgresql+asyncpg://dummy:dummy@localhost/dummy"
    HAS_DB = False
else:
    # Корректируем протокол для асинхронного драйвера
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif not DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Инициализируем движок
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Пытаемся создать таблицы только при наличии реальной базы
    if HAS_DB:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("INFO: Database tables verified successfully.")
        except Exception as e:
            print(f"ERROR: Failed to initialize database tables: {e}")
    yield
    await engine.dispose()

app = FastAPI(title="Rubezh API", lifespan=lifespan)

@app.get("/")
def read_root():
    return {
        "status": "alive", 
        "message": "Project Rubezh is stable.",
        "database_connected": HAS_DB
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
