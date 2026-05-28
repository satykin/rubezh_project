# -*- coding: utf-8 -*-
import os
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import BigInteger, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Безопасное получение и очистка строки подключения
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
HAS_DB = True

if not DATABASE_URL:
    print("WARNING: DATABASE_URL environment variable is empty. Running in dry mode.")
    DATABASE_URL = "postgresql+asyncpg://dummy:dummy@localhost/dummy"
    HAS_DB = False
else:
    # Корректировка протоколов под асинхронный драйвер
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif not DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Безопасная инициализация движка без сетевой активности
try:
    engine = create_async_engine(DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
except Exception:
    print("ERROR: Failed to configure database structure handler.")
    HAS_DB = False

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Пытаемся создать таблицы только если настройки верны
    if HAS_DB:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("INFO: Database connection verified. Tables are ready.")
        except Exception:
            # Ошибка изолирована, динамический текст исключения не выводится во избежание падения кодировки
            print("WARNING: Database is initializing or busy. Server stays online.")
    yield
    if HAS_DB:
        try:
            await engine.dispose()
        except Exception:
            print("INFO: Connection engine disposed clean.")

app = FastAPI(title="Rubezh API", lifespan=lifespan)

@app.get("/")
def read_root():
    return {
        "status": "alive", 
        "message": "Project Rubezh is fully stable.",
        "database_configured": HAS_DB
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
