# routes/puzzles.py
import random, asyncio, logging, time, requests, re
from fastapi import APIRouter, Query, Body, HTTPException, Request, Depends
from services.wiki import get_topic_terms
from services.puzzle_generator import generate_puzzle
from services.clue_fetcher import get_naver_clue
from db import db
from typing import Dict
from pymongo.collection import Collection
from datetime import datetime
from typing import Optional
from bson import ObjectId, errors as bson_errors
from models.models import PuzzleCreateRequest
from bson.errors import InvalidId
from pydantic import BaseModel

router = APIRouter()

@router.get("/user/profile")
async def get_user_profile(email: str):
    user = await db["users"].find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    return {
        "email": user["email"],
        "tier": user.get("tier", "없음"),
        "score": user.get("score", 0),
        "win_rate": user.get("win_rate", {})
    }
    
@router.get("/user/winrate")
async def get_user_winrate(request: Request) -> Dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")

    user_data = await db["users"].find_one({"email": user["email"]})
    if not user_data:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    win_rate = user_data.get("win_rate", {})

    # 전체 승률 계산
    total_win = sum([v.get("win", 0) for v in win_rate.values()])
    total_lose = sum([v.get("lose", 0) for v in win_rate.values()])
    win_rate["전체"] = {"win": total_win, "lose": total_lose}

    return {"win_rate": win_rate}

@router.get("/puzzles/words")
def get_words_by_topic(topic: str = Query("과학")):
    terms = get_topic_terms(topic)
    return {
        "topic": topic,
        "count": len(terms),
        "sample": terms[:10]
    }

@router.get("/puzzles/generate")
def generate_crossword(topic: str = "과학"):
    terms = get_topic_terms(topic)
    if not terms:
        return {"error": f"단어를 찾을 수 없습니다: {topic}"}

    # 랜덤 샘플 10개 선택
    selected = random.sample(terms, min(15, len(terms)))
    puzzle = generate_puzzle(selected)
    return puzzle

@router.get("/puzzle")
async def get_puzzle(topic: str = Query(...), level: int = Query(3)):
    print("🧩 퍼즐 API 호출됨!", topic, "level: ", level)

    terms = get_topic_terms(topic)
    if not terms:
        return {"error": f"{topic} 주제에서 단어를 찾을 수 없습니다."}
    
    word_count_by_level = {
        1: 6,
        2: 12,
        3: 18,
        4: 24,
        5: 30
    }
    word_count = word_count_by_level.get(level, 14)

    selected = random.sample(terms, min(word_count, len(terms)))
    puzzle_data = generate_puzzle(selected)


    # 단어별 설명 추가
    for word in puzzle_data["words"]:
        clue = await get_definition(word["word"])
        print(f"{word['word']} → {clue}")  # 이 로그가 터미널에 나와야 함
        word["clue"] = clue
    puzzle_data["words"] = [
    word for word in puzzle_data["words"]]
    #if word.get("clue") and word["clue"].strip()]
    
    puzzle_data["size"] = len(puzzle_data.get("board", []))
    puzzle_data["board"] = generate_board(puzzle_data["words"], puzzle_data["size"])
    
    puzzle_data["topic"] = topic
    puzzle_data["level"] = level

    return puzzle_data


def generate_board(words, size):
    board = [['' for _ in range(size)] for _ in range(size)]

    for word in words:
        x, y = word["y"], word["x"]
        direction = word["direction"]
        text = word["word"]

        # 좌표 유효성 & 범위 검사
        if x < 0 or y < 0 or direction not in {"across", "down"}:
            continue
        if direction == "across" and (y + len(text) > size):
            continue
        if direction == "down" and (x + len(text) > size):
            continue

        try:
            for i, ch in enumerate(text):
                if direction == "across":
                    board[x][y + i] = ch
                else:
                    board[x + i][y] = ch
        except IndexError:
            # 예외 방지: 배열 범위 벗어난 경우 무시
            continue

    return board


@router.post("/puzzle/save")
async def save_puzzle(data: dict = Body(...)):
    data["created_at"] = datetime.utcnow()
    result = await db["puzzles"].insert_one(data)
    return {"message": "저장 완료", "id": str(result.inserted_id)}

@router.get("/puzzles")
async def get_puzzle_list(
    topic: Optional[str] = Query(...),
    level: Optional[int] = Query(None)
):
    query = {}
    if topic:
        query["topic"] = topic
    if level is not None:
        query["level"] = level

    cursor = db["puzzles"].find(query).sort("created_at", -1)
    puzzles = []
    async for doc in cursor:
        puzzles.append({
            "id": str(doc["_id"]),
            "title": doc.get("title"),
            "topic": doc.get("topic"),
            "level": doc.get("level"),
            "created_at": doc.get("created_at")
        })

    return puzzles

@router.get("/user/{email}")
async def get_user(email: str):
    user = await db["users"].find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["_id"] = str(user["_id"])
    return user

@router.get("/users/me")
async def get_current_user(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")

    user_data = await db["users"].find_one({"email": user["email"]})
    if not user_data:
        raise HTTPException(status_code=404, detail="사용자 정보를 찾을 수 없습니다.")

    return {
        "email": user_data["email"],
        "tier": user_data.get("tier", "없음"),
        "score": user_data.get("score", 0),
        "win_rate": user_data.get("win_rate", {}),
    }


@router.get("/puzzle/{puzzle_id}")
async def get_puzzle(puzzle_id: str):
    try:
        object_id = ObjectId(puzzle_id)
    except:
        raise HTTPException(status_code=400, detail="잘못된 퍼즐 ID 형식입니다.")

    # 1. 사용자 퍼즐에서 먼저 찾기
    puzzle = await db["user_puzzles"].find_one({"_id": object_id})
    
    # 2. 없으면 공유 퍼즐에서 찾기
    if not puzzle:
        puzzle = await db["shared_puzzles"].find_one({"_id": object_id})
    
    if not puzzle:
        puzzle = await db["match_puzzles"].find_one({"_id": object_id})

    if not puzzle:
        raise HTTPException(status_code=404, detail="퍼즐을 찾을 수 없습니다.")

    puzzle["_id"] = str(puzzle["_id"])
    return puzzle

@router.get("/puzzle/user/{puzzle_id}")
async def get_user_puzzle(puzzle_id: str, request: Request):
    from bson import ObjectId
    user = request.state.user
    puzzle = await db["user_puzzles"].find_one({
        "_id": ObjectId(puzzle_id),
        "author": user["email"]
    })
    if not puzzle:
        raise HTTPException(status_code=404, detail="퍼즐을 찾을 수 없습니다")
    puzzle["id"] = str(puzzle["_id"])
    del puzzle["_id"]
    return puzzle


@router.post("/save-puzzle")
async def save_puzzle(data: PuzzleCreateRequest, request: Request):
    puzzle = data.dict()
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다")
    puzzle["author"] = user["email"]
    result = await db["puzzles"].insert_one(puzzle)
    return {"id": str(result.inserted_id)}


@router.post("/save-user-puzzle")
async def save_user_puzzle(data: PuzzleCreateRequest, request: Request):
    puzzle = data.dict()
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다")

    puzzle["author"] = user["email"]
    result = await db["user_puzzles"].insert_one(puzzle)
    return {"id": str(result.inserted_id)}

@router.put("/save-user-puzzle/{puzzle_id}")
async def update_user_puzzle(puzzle_id: str, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")

    updated_data = await request.json()

    result = await db["user_puzzles"].update_one(
        {"_id": ObjectId(puzzle_id), "author": user["email"]},
        {"$set": updated_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="퍼즐을 찾을 수 없거나 수정 권한이 없습니다.")

    return {"message": "수정 성공"}

@router.get("/my-puzzles")
async def get_my_puzzles(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")
    puzzles = await db["user_puzzles"].find({"author": user["email"]}).to_list(100)
    for p in puzzles:
        p["id"] = str(p["_id"])
        del p["_id"]
    return puzzles

class Puzzle(BaseModel):
    title: str
    topic: str
    level: int
    gridSize: int
    board: list
    words: list
    author: Optional[str] = None

@router.post("/shared_puzzles")
async def share_puzzle(puzzle: Puzzle, request: Request):
    try:
        user = getattr(request.state, "user", None)
        if not user:
            print("⚠️ 인증 안 된 사용자 요청")
            raise HTTPException(status_code=401, detail="인증 필요")

        
        # 퍼즐 데이터 변환
        puzzle_data = puzzle.dict()
        puzzle_data.pop('_id', None)  # safety check
        puzzle_data["shared_by"] = user["email"]
        puzzle_data["likes"] = puzzle_data.get("likes", [])
        puzzle_data["solved_by"] = puzzle_data.get("solved_by", [])
        if "gridSize" not in puzzle_data and "board" in puzzle_data:
    # 자동 추정 (예: 보드의 행 길이로 추정)
            puzzle_data["gridSize"] = len(puzzle_data["board"])


        # 중복 여부 검사: title, topic, level, board, words 전부 동일한 퍼즐 있는지 확인
        duplicate_check = await db["shared_puzzles"].find_one({
            "title": puzzle_data["title"],
            "topic": puzzle_data["topic"],
            "level": puzzle_data["level"],
            "board": puzzle_data["board"],
            "words": puzzle_data["words"],
        })

        if duplicate_check:
            print("⚠️ 이미 공유된 퍼즐입니다.")
            raise HTTPException(status_code=409, detail="이미 공유된 퍼즐입니다.")

        # 삽입
        result = await db["shared_puzzles"].insert_one(puzzle_data)
        print("✅ 퍼즐 공유 성공:", result.inserted_id)
        return {"message": "공유 성공", "id": str(result.inserted_id)}

    except HTTPException:
        raise  # 위에서 raise한 HTTPException은 그대로 다시 raise
    except Exception as e:
        print("❌ 공유 중 오류 발생:", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류 발생")

@router.get("/user/me")
async def get_current_user(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증되지 않았습니다")
    return {"email": user["email"]}

@router.get("/shared_puzzles")
async def get_shared_puzzles(sort_by: str = Query("recent")):
    sort_by = (sort_by or "recent").lower()

    # 정렬 스테이지 선택
    if sort_by == "likes":
        sort_stage = {"$sort": {"likesCount": -1, "_id": -1}}  # 좋아요 같으면 최신순 보조정렬
    else:
        sort_stage = {"$sort": {"_id": -1}}  # recent

    pipeline = [
        # likesCount를 항상 숫자로
        {
            "$addFields": {
                "likesCount": {
                    "$cond": [
                        {"$isArray": "$likes"},
                        {"$size": {"$ifNull": ["$likes", []]}},
                        {"$ifNull": ["$likes", 0]}  # likes가 숫자거나 null/미존재일 때
                    ]
                }
            }
        },
        sort_stage,
        {
            "$project": {
                "title": 1,
                "topic": 1,
                "level": 1,
                "shared_by": 1,
                "likes": 1,
                "likesCount": 1,
                "solved_by": 1,
            }
        },
    ]

    puzzles = []
    async for doc in db["shared_puzzles"].aggregate(pipeline):
        doc["_id"] = str(doc["_id"])
        puzzles.append(doc)
    return puzzles

@router.post("/shared_puzzles/{puzzle_id}/like")
async def like_puzzle(puzzle_id: str, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")

    email = user["email"]

    # 퍼즐 불러오기
    puzzle = await db["shared_puzzles"].find_one({"_id": ObjectId(puzzle_id)})
    if not puzzle:
        raise HTTPException(status_code=404, detail="퍼즐을 찾을 수 없습니다.")

    # 👉 여기! likes가 숫자면 배열로 초기화
    likes = puzzle.get("likes", [])
    if not isinstance(likes, list):
        likes = []

    # 이미 누른 경우 차단
    if email in puzzle.get("likes", []):
        # 좋아요 취소
        await db["shared_puzzles"].update_one(
            {"_id": ObjectId(puzzle_id)},
            {"$pull": {"likes": email}}
        )
    else:
        # 좋아요 추가
        await db["shared_puzzles"].update_one(
            {"_id": ObjectId(puzzle_id)},
            {"$addToSet": {"likes": email}}
        )
        
    updated = await db["shared_puzzles"].find_one({"_id": ObjectId(puzzle_id)})
    updated["_id"] = str(updated["_id"])
    return updated

@router.get("/shared_puzzles/{puzzle_id}")
async def get_shared_puzzle(puzzle_id: str):
    puzzle = await db["shared_puzzles"].find_one({"_id": ObjectId(puzzle_id)})
    if not puzzle:
        raise HTTPException(status_code=404, detail="퍼즐을 찾을 수 없습니다.")

    puzzle["_id"] = str(puzzle["_id"])

    raw_likes = puzzle.get("likes", [])
    if not isinstance(raw_likes, list):
        raw_likes = []
    puzzle["likes"] = raw_likes

    puzzle["solved_by"] = puzzle.get("solved_by", [])
    puzzle["liked_by"] = puzzle.get("liked_by", [])

    return puzzle

@router.post("/shared_puzzles/{puzzle_id}/submit")
async def submit_shared_puzzle(puzzle_id: str, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="인증 필요")

    try:
        oid = ObjectId(puzzle_id)
    except:
        raise HTTPException(status_code=400, detail="잘못된 퍼즐 ID")

    email = user["email"]
    data = await request.json()
    started_at = data.get("started_at")  # 클라이언트 시작 시간 (ms)

    if not started_at:
        raise HTTPException(status_code=400, detail="시작 시간이 필요합니다.")

    now_ms = int(time.time() * 1000)  # ✅ 현재 시간 (ms)
    elapsed_sec = int((now_ms - started_at) / 1000)  # 경과 시간 (초)

    if elapsed_sec < 0:
        elapsed_sec = 0  # 음수 방지 (시간 차이 있을 경우)

    # 이미 푼 경우 중복 저장 방지
    puzzle = await db["shared_puzzles"].find_one({"_id": oid})
    for entry in puzzle.get("solved_by", []):
        if entry["email"] == email:
            return {"message": "이미 기록됨"}

    await db["shared_puzzles"].update_one(
        {"_id": oid},
        {"$push": {"solved_by": {"email": email, "time": elapsed_sec}}}
    )

    return {"message": "기록됨", "time": elapsed_sec}

@router.get("/ranking")
async def get_ranking():
    users_cursor = db["users"].find({}, {"email": 1, "tier": 1, "score": 1}).sort("score", -1).limit(10)
    ranking = []
    idx = 1
    async for user in users_cursor:
        ranking.append({
            "rank": idx,
            "email": user["email"],
            "tier": user.get("tier", "없음"),
            "score": user.get("score", 0)
        })
        idx += 1
    return ranking

@router.get("/ranking/all")
async def get_ranking():
    users_cursor = db["users"].find({}, {"email": 1, "tier": 1, "score": 1}).sort("score", -1)
    ranking = []
    idx = 1
    async for user in users_cursor:
        ranking.append({
            "rank": idx,
            "email": user["email"],
            "tier": user.get("tier", "없음"),
            "score": user.get("score", 0)
        })
        idx += 1
    return ranking

@router.delete("/user_puzzles/{puzzle_id}")
async def delete_user_puzzle(puzzle_id: str, request: Request):
    try:
        user = getattr(request.state, "user", None)
        print("✅ delete_user_puzzle 진입")
        print("🔐 사용자 정보:", user)

        if not user or "email" not in user:
            raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다.")

        try:
            object_id = ObjectId(puzzle_id)
        except InvalidId:
            print("❌ ObjectId 변환 실패:", puzzle_id)
            raise HTTPException(status_code=400, detail="퍼즐 ID 형식이 잘못되었습니다.")

        result = await db["user_puzzles"].delete_one({
            "_id": object_id,
            "author": user["email"]
        })

        print("🗑 삭제 결과:", result.deleted_count)

        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="퍼즐을 찾을 수 없거나 삭제 권한이 없습니다.")

        return {"message": "삭제 성공"}

    except Exception as e:
        import traceback
        print("🔥 퍼즐 삭제 중 오류 발생:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="서버 내부 오류입니다.")
    
@router.get("/definition")
async def get_definition(word: str, retries: int = 3, delay: float = 0.5):
    cleaned_word = preprocess_word(word)
    url = f"https://ko.wikipedia.org/api/rest_v1/page/summary/{cleaned_word}"

    headers = {
        "User-Agent": "CrosswordApp/1.0 (contact@example.com)"
    }

    for i in range(retries):
        try:
            res = requests.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                meaning = data.get("extract", "").strip()
                title = data.get("title") or ""

                meaning = mask_answer(meaning, word, aliases=[title])
                meaning = clean_text(meaning)

                if meaning and not meaning.endswith(("다.", ".", "!", "?")):
                    meaning += "."

                return meaning

            elif res.status_code == 429:
                wait_time = 2 ** i
                print(f"⏳ 429 오류: {word} → {wait_time}초 후 재시도...")
                await asyncio.sleep(wait_time)

            else:
                print(f"❌ 요청 실패 ({res.status_code}) → {word}")
                break

        except Exception as e:
            print(f"❌ 예외 발생: {e} → {word}")
            break

    return {"meaning": "뜻을 찾을 수 없습니다."}

def mask_answer(text: str, answer: str, aliases: list[str] | None = None) -> str:
    """뜻 텍스트에서 정답/유사표기를 글자 수만큼 '*'로 마스킹"""
    if not text:
        return ""
    targets = set()

    # 기본 타깃: 정답과 공백 제거 버전
    if answer:
        targets.add(answer.strip())
        targets.add(answer.strip().replace(" ", ""))

    # 추가 타깃들(타이틀 등)
    for a in aliases or []:
        if not a:
            continue
        a = a.strip()
        if not a:
            continue
        targets.add(a)
        targets.add(a.replace(" ", ""))

    # 긴 문자열부터 치환(부분일치로 인한 꼬임 방지)
    for t in sorted(targets, key=len, reverse=True):
        mask = "*" * len(t)  # 글자 수만큼 '*' 생성
        text = re.sub(re.escape(t), mask, text, flags=re.IGNORECASE)

    return text

def clean_text(text: str) -> str:
    if not text:
        return ""
    # 괄호 안 내용 제거
    text = re.sub(r"\([^)]*\)", "", text)  # ( ... ) 삭제
    text = re.sub(r"（[^）]*）", "", text)  # 전각 괄호（ ... ）삭제
    # 양쪽 공백 정리
    return text.strip()

def preprocess_word(word: str) -> str:
    """URL에 들어가기 적절하도록 전처리"""
    return word.strip().replace(" ", "_")