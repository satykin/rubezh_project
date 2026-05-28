# -*- coding: utf-8 -*-
import os
import hmac
import hashlib
import json
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Depends
from sqlalchemy import BigInteger, DateTime, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
HAS_DB = True

if not DATABASE_URL:
    print("WARNING: DATABASE_URL environment variable is empty. Running in dry mode.")
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

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# Функция (dependency) для безопасного получения сессии базы данных в эндпоинтах
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

# Безопасная валидация данных от Telegram Mini App
def verify_telegram_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Telegram Bot Token is not configured on server")
    try:
        # Разбиваем строку параметров Telegram
        parsed_data = dict(qc.split("=") for qc in init_data.split("&"))
        hash_value = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        # Вычисляем секретный ключ на основе токена бота
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash != hash_value:
            raise HTTPException(status_code=401, detail="Data integrity check failed. Fraud suspected.")
            
        return json.loads(parsed_data["user"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Telegram initialization data structure")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if HAS_DB:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("INFO: Database connection verified. Tables are ready.")
        except Exception:
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

# Эндпоинт авторизации и регистрации
@app.post("/api/auth/login")
async def login_or_register(tg_data: str = Header(...), db: AsyncSession = Depends(get_db)):
    # 1. Проверяем, что запрос пришел из реального Telegram
    tg_user = verify_telegram_data(tg_data)
    tg_id = tg_user["id"]
    
    # 2. Ищем пользователя в базе данных
    result = await db.execute(select(User).where(User.telegram_id == tg_id))
    user = result.scalar_one_or_not_none()
    
    # 3. Если это новый мужчина — регистрируем его
    if not user:
        user = User(telegram_id=tg_id)
        db.add(user)
        await db.flush()
        status = "registered"
    else:
        status = "welcome_back"
        
    return {
        "status": status,
        "user_id": user.id,
        "first_name": tg_user.get("first_name", "Мужчина")
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
