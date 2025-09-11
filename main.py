from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from services.naver import search_encyclopedia
from routes import auth, puzzles, match
from dotenv import load_dotenv
from services.wiki import router as wiki_router
from middlewares.auth_middleware import AuthMiddleware
from db import db  # ✅ 이미 연결된 db 객체 사용
from contextlib import asynccontextmanager
import logging

load_dotenv()
app = FastAPI()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("uvicorn")
    result = await db["shared_puzzles"].update_many(
        {"likes": {"$not": {"$type": "array"}}},  # 배열이 아닌 값 모두 대상
        {"$set": {"likes": []}}
    )
    result = await db["users"].update_many(
        {"score": {"$exists": False}},
        {"$set": {"score": 0}}
    )
    result = await db["users"].update_many(
        {"win_rate": {"$exists": False}},
        {"$set": {"win_rate": {"과학": { "win": 0, "lose": 0 },"사회": { "win": 0, "lose": 0 },"국어": { "win": 0, "lose": 0 },"수학": { "win": 0, "lose": 0 }}}}
    )
    yield
    

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://frontend-e9lm.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthMiddleware)

app.include_router(auth.router)
app.include_router(puzzles.router, prefix="/api")
app.include_router(wiki_router, prefix="/api")
app.include_router(match.router)
