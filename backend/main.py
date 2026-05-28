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

# Защита от запуска без базы данных
if not DATABASE_URL:
    print("⚠️ ВНИМАНИЕ: Переменная DATABASE_URL не найдена! Проверь настройки в Railway.")
    # Временная заглушка, чтобы сервер не падал при сборке без переменных
    DATABASE_URL = "postgresql+asyncpg://dummy:dummy@localhost/dummy"

# Фикс для Railway протокола
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Создаем движок
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
    # Таблицы создаем только если у нас реальная база, а не заглушка
    if "dummy" not in os.getenv("DATABASE_URL", ""):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="Рубеж API", lifespan=lifespan)

@app.get("/")
def read_root():
    return {
        "status": "alive", 
        "message": "Project Rubezh is alive. Connection secure."
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
