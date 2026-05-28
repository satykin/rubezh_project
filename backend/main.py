# -*- coding: utf-8 -*-
import os
import hmac
import hashlib
import json
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, select, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
HAS_DB = True

if not DATABASE_URL:
    print("WARNING: DATABASE_URL variable is empty. Running in dry mode.")
    DATABASE_URL = "postgresql+asyncpg://dummy:dummy@localhost/dummy"
    HAS_DB = False
else:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif not DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

# Таблица пользователей
class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# Таблица логов трекера (Энергия / Раздражение / Пустота)
class TrackerLog(Base):
    __tablename__ = "tracker_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    energy: Mapped[int] = mapped_column()
    irritation: Mapped[int] = mapped_column()
    emptiness: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# Pydantic-схема для валидации входящих данных трекера
class TrackerInput(BaseModel):
    energy: int = Field(..., ge=1, le=10)
    irritation: int = Field(..., ge=1, le=10)
    emptiness: int = Field(..., ge=1, le=10)

async def get_db():
    if not HAS_DB:
        raise HTTPException(status_code=500, detail="Database not configured")
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

def verify_telegram_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Telegram Bot Token is not configured")
    try:
        parsed_data = dict(qc.split("=") for qc in init_data.split("&"))
        hash_value = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash != hash_value:
            raise HTTPException(status_code=401, detail="Verification failed")
            
        return json.loads(parsed_data["user"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session data")

# Вспомогательная функция для эндпоинтов: автоматически определяет юзера по Telegram-заголовку
async def get_current_user(tg_data: str = Header(...), db: AsyncSession = Depends(get_db)) -> User:
    tg_user = verify_telegram_data(tg_data)
    result = await db.execute(select(User).where(User.telegram_id == tg_user["id"]))
    user = result.scalar_one_or_not_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not registered. Please log in first.")
    return user

@asynccontextmanager
async def lifespan(app: FastAPI):
    if HAS_DB:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("INFO: Database connection verified. All tables created successfully.")
        except Exception:
            print("WARNING: Database is busy. Tables deployment skipped.")
    yield
    if HAS_DB:
        await engine.dispose()

app = FastAPI(title="Rubezh API", lifespan=lifespan)

@app.get("/")
def read_root():
    return {
        "status": "alive", 
        "database_configured": HAS_DB
    }

# 1. Эндпоинт авторизации/регистрации
@app.post("/api/auth/login")
async def login_or_register(tg_data: str = Header(...), db: AsyncSession = Depends(get_db)):
    tg_user = verify_telegram_data(tg_data)
    tg_id = tg_user["id"]
    
    result = await db.execute(select(User).where(User.telegram_id == tg_id))
    user = result.scalar_one_or_not_none()
    
    if not user:
        user = User(telegram_id=tg_id)
        db.add(user)
        await db.flush()
        status = "registered"
    else:
        status = "welcome_back"
        
    return {"status": status, "user_id": user.id, "first_name": tg_user.get("first_name", "User")}

# 2. Эндпоинт: Сохранить новое состояние в трекер
@app.post("/api/tracker/log")
async def save_tracker_log(
    payload: TrackerInput, 
    current_user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    new_log = TrackerLog(
        user_id=current_user.id,
        energy=payload.energy,
        irritation=payload.irritation,
        emptiness=payload.emptiness
    )
    db.add(new_log)
    return {"status": "success", "message": "State tracked successfully."}

# 3. Эндпоинт: Получить историю трекера для графиков
@app.get("/api/tracker/history")
async def get_tracker_history(
    current_user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(TrackerLog)
        .where(TrackerLog.user_id == current_user.id)
        .order_by(TrackerLog.created_at.desc())
    )
    logs = result.scalars().all()
    
    return [
        {
            "id": log.id,
            "energy": log.energy,
            "irritation": log.irritation,
            "emptiness": log.emptiness,
            "date": log.created_at.isoformat()
        } for log in logs
    ]

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
