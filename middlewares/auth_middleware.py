from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from utils.token import decode_token

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = request.headers.get("Authorization")
        print("📥 토큰 수신:", token)
        if token and token.startswith("Bearer "):
            token = token.replace("Bearer ", "")
            user_data = decode_token(token)
            if user_data:
                request.state.user = user_data
                print("✅ 사용자 인증 성공:", user_data)
            else:
                print("토큰 디코드 실패")
        else:
            print("토근없음")
        return await call_next(request)
