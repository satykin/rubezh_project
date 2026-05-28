# -*- coding: utf-8 -*-
import os
import hmac
import hashlib
import json
import uvicorn
import httpx
from datetime import datetime
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, select, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# --- КАСКАД ДВУХ МОДЕЛЕЙ ИИ ---
AI_QWEN_KEY = os.getenv("AI_QWEN_KEY", "").strip()
AI_QWEN_URL = os.getenv("AI_QWEN_URL", "https://openrouter.ai/api/v1").strip()
AI_QWEN_MODEL = os.getenv("AI_QWEN_MODEL", "qwen/qwen-2.5-72b-instruct").strip()

AI_DEEPSEEK_KEY = os.getenv("AI_DEEPSEEK_KEY", "").strip()
AI_DEEPSEEK_URL = os.getenv("AI_DEEPSEEK_URL", "https://api.deepseek.com/v1").strip()
AI_DEEPSEEK_MODEL = os.getenv("AI_DEEPSEEK_MODEL", "deepseek-chat").strip()

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

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TrackerLog(Base):
    __tablename__ = "tracker_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    energy: Mapped[int] = mapped_column()
    irritation: Mapped[int] = mapped_column()
    emptiness: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TrackerInput(BaseModel):
    energy: int = Field(..., ge=1, le=10)
    irritation: int = Field(..., ge=1, le=10)
    emptiness: int = Field(..., ge=1, le=10)

class ChatInput(BaseModel):
    message: str

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
        params = dict(parse_qsl(init_data))
        if "hash" not in params:
            raise HTTPException(status_code=401, detail="Missing hash")
        hash_value = params.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash != hash_value:
            raise HTTPException(status_code=401, detail="Verification failed")
        return json.loads(params["user"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session data")

async def get_current_user(tg_data: str = Header(...), db: AsyncSession = Depends(get_db)) -> User:
    tg_user = verify_telegram_data(tg_data)
    result = await db.execute(select(User).where(User.telegram_id == tg_user["id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not registered")
    return user

async def call_ai_api(base_url: str, api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.65
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{base_url}/chat/completions", headers=headers, json=data, timeout=12.0)
        if response.status_code != 200:
            raise Exception(f"Provider status code: {response.status_code}")
        result_json = response.json()
        return result_json["choices"][0]["message"]["content"]

@asynccontextmanager
async def lifespan(app: FastAPI):
    if HAS_DB:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("INFO: Database initialized.")
        except Exception as e:
            print(f"WARNING: DB initialization error: {e}")
    yield
    if HAS_DB:
        await engine.dispose()

app = FastAPI(title="Rubezh API", lifespan=lifespan)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h3>Frontend file 'index.html' not found.</h3>"

@app.post("/api/auth/login")
async def login_or_register(tg_data: str = Header(...), db: AsyncSession = Depends(get_db)):
    tg_user = verify_telegram_data(tg_data)
    result = await db.execute(select(User).where(User.telegram_id == tg_user["id"]))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=tg_user["id"])
        db.add(user)
        await db.flush()
        status = "registered"
    else:
        status = "welcome_back"
    return {"status": status, "user_id": user.id, "first_name": tg_user.get("first_name", "User")}

@app.post("/api/tracker/log")
async def save_tracker_log(payload: TrackerInput, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    new_log = TrackerLog(user_id=current_user.id, energy=payload.energy, irritation=payload.irritation, emptiness=payload.emptiness)
    db.add(new_log)
    return {"status": "success"}

@app.get("/api/tracker/history")
async def get_tracker_history(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TrackerLog).where(TrackerLog.user_id == current_user.id).order_by(TrackerLog.created_at.desc()))
    logs = result.scalars().all()
    return [{"id": log.id, "energy": log.energy, "irritation": log.irritation, "emptiness": log.emptiness, "date": log.created_at.isoformat()} for log in logs]

@app.post("/api/ai/chat")
async def ai_brother_chat(payload: ChatInput, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user_text = payload.message.lower().strip()

    # 1. МОДЕРАЦИЯ КРИТИЧЕСКИХ ЗАПРОСОВ (Перенаправление)
    critical_keywords = [
        "суицид", "убить себя", "покончить с собой", "повесить", "вскрыть вены", 
        "спрыгнуть", "умереть", "таблетки", "наглотаться", "смерть", "резать", 
        "убью", "расправиться", "насилие", "прирезать", "зарезать"
    ]
    if any(keyword in user_text for keyword in critical_keywords):
        return {
            "reply": (
                "Брат, стоп. Здесь рамки цифрового помощника заканчиваются. "
                "Если тебя накрыло так, что ты думаешь о непоправимом или теряешь контроль над безопасностью — "
                "не держи это в себе и не жди ответа от робота.\n\n"
                "Вот люди, которые вытащат из этой петли прямо сейчас, профессионально и анонимно:\n"
                "📞 Единый телефон доверия: 8 (800) 333-44-34\n"
                "📞 Горячая линия психологической помощи: 8 (800) 200-01-22\n"
                "Сделай этот звонок. Это не слабость, это нормальный тактический маневр мужчины, попавшего в засаду."
            )
        }

    # 2. СБОР КОНТЕКСТА СОСТОЯНИЯ
    result = await db.execute(
        select(TrackerLog).where(TrackerLog.user_id == current_user.id).order_by(TrackerLog.created_at.desc()).limit(1)
    )
    last_log = result.scalar_one_or_none()
    context_string = "Данные трекера отсутствуют."
    if last_log:
        context_string = f"Энергия: {last_log.energy}/10, Раздражение: {last_log.irritation}/10, Пустота: {last_log.emptiness}/10."

    # 3. СИСТЕМНЫЙ ПРОМПТ (МАТ + ЗАПРЕТ ДИАГНОЗОВ)
    system_prompt = (
        "Ты — ИИ Брат, цифровой ментор для мужчин, переживающих жесткий кризис, выгорание и стресс. "
        "Твой стиль: спартанский, прагматичный, поддерживающий, но строгий. Говори коротко, емко, по делу.\n\n"
        "ПРАВИЛО ЯЗЫКА: Для создания честной, аутентичной мужской атмосферы разговора без цензуры "
        "умеренное использование крепкого словца (мата) приветствуется в пределах разумного. "
        "Используй мат к месту, для акцента на проблеме, но не превращай речь в бессмысленное поливание грязью.\n\n"
        "КРИТИЧЕСКОЕ ТАБУ НА ДИАГНОЗЫ: Тебе строжайше запрещено ставить медицинские или психиатрические "
        "диагнозы (например, забудь слова: 'у тебя клиническая депрессия', 'это биполярка', 'тебе нужно лечить расстройство'). "
        "Избегай любых формулировок, создающих ложное впечатление медицинского лечения. Ты не врач, ты старший товарищ. "
        "Оценивай ситуацию через призму усталости, износа процессора, внешних факторов и конкретных физических действий.\n\n"
        f"Текущее состояние мужчины из логов: {context_string}"
    )

    # 4. FAILOVER КАСКАД
    # Попытка 1: Qwen
    if AI_QWEN_KEY:
        try:
            reply = await call_ai_api(AI_QWEN_URL, AI_QWEN_KEY, AI_QWEN_MODEL, system_prompt, payload.message)
            return {"reply": reply}
        except Exception as e:
            print(f"ERROR: Qwen failed: {e}. Switching to DeepSeek...")

    # Попытка 2: DeepSeek
    if AI_DEEPSEEK_KEY:
        try:
            reply = await call_ai_api(AI_DEEPSEEK_URL, AI_DEEPSEEK_KEY, AI_DEEPSEEK_MODEL, system_prompt, payload.message)
            return {"reply": reply}
        except Exception as e:
            print(f"CRITICAL: DeepSeek failed: {e}")

    raise HTTPException(status_code=503, detail="ИИ-модули на техобслуживании. Напиши через пару минут.")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
