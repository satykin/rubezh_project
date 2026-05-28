# -*- coding: utf-8 -*-
import os
import uvicorn
from fastapi import FastAPI

app = FastAPI(title="Рубеж API")

@app.get("/")
def read_root():
    return {
        "status": "alive", 
        "message": "Project Rubezh is alive. Ready for database."
    }

# Этот блок заставит приложение работать бесконечно и слушать нужный порт
if __name__ == "__main__":
    # Railway передает порт в переменную окружения PORT. Если запускаешь локально — включится 8000
    port = int(os.getenv("PORT", 8000))
    
    # host="0.0.0.0" жестко необходим, чтобы сервер принимал внешние запросы от Railway
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
