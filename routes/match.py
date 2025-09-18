from fastapi import APIRouter, WebSocket, HTTPException, Query, Request
from services.match_manager import MatchManager

router = APIRouter()
match_manager = MatchManager()

@router.websocket("/ws/match")
async def websocket_match(websocket: WebSocket):
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        email = data.get("value")
        tier = data.get("tier")
        print(email, tier)
        if not email or not tier:
            await websocket.send_json({"error": "이메일 또는 티어 정보가 없습니다."})
            await websocket.close()
            return

        await match_manager.enqueue(websocket)

    except Exception as e:
        print(f"❌ WebSocket 수신 중 오류 발생: {e}")
        await websocket.close()
    
@router.post("/match/leave")
async def http_leave(email: str = Query(...)):
    result = await match_manager.force_leave_by_email(email)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "force leave failed"))
    return {"ok": True}


@router.post("/api/match/leave")
async def leave_match(request: Request):
    try:
        email = request.query_params.get("email")
        if email:
            result = await match_manager.force_leave_by_email(email)
            return {"status": "ok", "detail": result}
        return {"status": "error", "detail": "email 누락"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}