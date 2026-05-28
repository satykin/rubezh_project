# -*- coding: utf-8 -*-
import os
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import BigInteger, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 1. Настройка подключения к PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")

# Фикс для Railway: подменяем протокол на асинхронный драйвер asyncpg
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Создаем асинхронный движок базы данных
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# 2. Описание таблиц (Модели SQLAlchemy)
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# 3. Автоматическое создание таблиц при старте сервера
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Этот блок выполняется ОДИН РАЗ при запуске контейнера
    async with engine.begin() as conn:
        # Создает таблицы в базе данных, если их там еще нет
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Логика при выключении сервера (закрываем соединения)
    await engine.dispose()

# 4. Инициализация приложения
app = FastAPI(title="Рубеж API", lifespan=lifespan)

@app.get("/")
def read_root():
    return {
        "status": "alive", 
        "message": "Project Rubezh is alive. Database connected and users table initialized."
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
