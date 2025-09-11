from fastapi import APIRouter, HTTPException
from models.user import UserCreate
from db import db
import bcrypt
from utils.token import create_token
from pydantic import BaseModel


router = APIRouter(prefix="/api/auth")

class UserCreate(BaseModel):
    email: str
    password: str

@router.post("/register")
async def register(user: UserCreate):
    try:
        print("📥 받은 요청:", user)
        existing = await db.users.find_one({"email": user.email})
        if existing:
            raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다.")

        hashed_pw = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
        user_doc = {
            "email": user.email,
            "hashed_password": hashed_pw.decode('utf-8'),
            "tier": "없음",
            "score": 0,
            "win_rate": { "과학": { "win": 0, "lose": 0 }, "사회": { "win": 0, "lose": 0 }, "국어": { "win": 0, "lose": 0 }, "수학": { "win": 0, "lose": 0 }},
        }
        await db.users.insert_one(user_doc)
        return {"message": "회원가입 성공"}

    except Exception as e:
        print("❌ 서버 오류 발생:", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류")


@router.post("/login")
async def login(user: UserCreate):
    existing_user = await db.users.find_one({"email": user.email})
    if not existing_user:
        raise HTTPException(status_code=401, detail="이메일이 존재하지 않습니다.")

    valid = bcrypt.checkpw(user.password.encode('utf-8'), existing_user["hashed_password"].encode('utf-8'))
    if not valid:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")

    token_data = {
        "email": existing_user["email"],
        "tier": existing_user.get("tier", "없음"),
        "score": existing_user.get("score", 0),
        "win_rate": existing_user.get("wint_rate", { "과학": { "win": 0, "lose": 0 }, "사회": { "win": 0, "lose": 0 }, "국어": { "win": 0, "lose": 0 }, "수학": { "win": 0, "lose": 0 }}),
    }
    access_token = create_token(token_data)
    
    token = create_token({"email": user.email})
    
    return {"message": "로그인 성공", "email": user.email, "access_token": access_token, "token": token, "user": token_data}
