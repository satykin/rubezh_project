from fastapi import FastAPI

app = FastAPI(title="Рубеж API")

@app.get("/")
def read_root():
    return {
        "status": "alive", 
        "message": "Проект Рубеж дышит. База готова к развертыванию."
    }