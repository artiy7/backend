import random
from typing import List, Tuple, Dict, Optional

from services.definition import get_definition
from services.wiki import get_topic_terms
from db import db

word_count_by_level = {
    1: 6,
    2: 12,
    3: 18,
    4: 24,
    5: 30
}

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

async def generate_random_puzzle_for_match():
    print("🔧 퍼즐 생성기 호출됨")
    topics = ["수학", "과학", "사회", "국어"]
    levels = [2, 3]

    topic = random.choice(topics)
    level = random.choice(levels)

    terms = get_topic_terms(topic)
    if not terms:
        return {"error": f"{topic} 주제에서 단어를 찾을 수 없습니다."}

    word_count = word_count_by_level.get(level, 14)
    selected = random.sample(terms, min(word_count, len(terms)))

    puzzle_data = generate_puzzle(selected)

    # 단어별 설명 추가 (await 필요)
    for word in puzzle_data["words"]:
        clue = await get_definition(word["word"])
        word["clue"] = clue

    # 유효한 단어만 남기기
    puzzle_data["words"] = [
        word for word in puzzle_data["words"]
    ]

    # 보드 생성
    puzzle_data["size"] = len(puzzle_data.get("board", []))
    puzzle_data["board"] = generate_board(puzzle_data["words"], puzzle_data["size"])
    puzzle_data["topic"] = topic
    puzzle_data["level"] = level
    
    result = await db["match_puzzles"].insert_one(puzzle_data)
    puzzle_data["_id"] = str(result.inserted_id)


    return puzzle_data

def generate_puzzle(words: List[str], size: int = 15) -> Dict:
    board = [["" for _ in range(size)] for _ in range(size)]
    placed = []

    def is_valid(x: int, y: int) -> bool:
        return 0 <= x < size and 0 <= y < size

    def get_cell(x: int, y: int) -> Optional[str]:
        return board[y][x] if is_valid(x, y) else None

    def fits(word: str, x: int, y: int, direction: str) -> bool:
        for i in range(len(word)):
            xi = x + i if direction == "across" else x
            yi = y if direction == "across" else y + i

            if not is_valid(xi, yi):
                return False

            cell = get_cell(xi, yi)
            if cell != "" and cell != word[i]:
                return False

            # Check surroundings
            if cell == "":
                # Horizontal neighbors for vertical word, and vice versa
                if direction == "across":
                    for dy in [-1, 1]:
                        if is_valid(xi, yi + dy) and board[yi + dy][xi] != "":
                            return False
                else:
                    for dx in [-1, 1]:
                        if is_valid(xi + dx, yi) and board[yi][xi + dx] != "":
                            return False

        # Check leading/trailing cells
        before = (x - 1, y) if direction == "across" else (x, y - 1)
        after = (x + len(word), y) if direction == "across" else (x, y + len(word))

        if is_valid(*before) and get_cell(*before) != "":
            return False
        if is_valid(*after) and get_cell(*after) != "":
            return False

        return True

    def score(word: str, x: int, y: int, direction: str) -> int:
        return sum(
            get_cell(x + i if direction == "across" else x,
                     y if direction == "across" else y + i) == ch
            for i, ch in enumerate(word)
        )

    def place_word(word: str, x: int, y: int, direction: str):
        for i, ch in enumerate(word):
            xi = x + i if direction == "across" else x
            yi = y if direction == "across" else y + i
            board[yi][xi] = ch
        placed.append({"word": word, "x": x, "y": y, "direction": direction})

    def find_best_position(word: str) -> Optional[Tuple[int, int, str]]:
        best = None
        best_score = -1

        for pw in placed:
            for i, c1 in enumerate(pw["word"]):
                for j, c2 in enumerate(word):
                    if c1 != c2:
                        continue

                    if pw["direction"] == "across":
                        x = pw["x"] + i
                        y = pw["y"] - j
                        direction = "down"
                    else:
                        x = pw["x"] - j
                        y = pw["y"] + i
                        direction = "across"

                    if fits(word, x, y, direction):
                        s = score(word, x, y, direction)
                        if s > best_score:
                            best = (x, y, direction)
                            best_score = s

        return best

    if not words:
        return {"board": board, "words": placed}

    words.sort(key=lambda w: -len(w))  # Place longer words first

    # Place first word at center
    first = words.pop(0)
    start_x = (size - len(first)) // 2
    start_y = size // 2
    place_word(first, start_x, start_y, "across")

    for word in words:
        pos = find_best_position(word)
        if pos:
            place_word(word, *pos)
        else:
            # Try random positions as fallback
            for _ in range(100):
                direction = random.choice(["across", "down"])
                x = random.randint(0, size - len(word) if direction == "across" else size - 1)
                y = random.randint(0, size - len(word) if direction == "down" else size - 1)
                if fits(word, x, y, direction):
                    place_word(word, x, y, direction)
                    break

    return {"board": board, "words": placed}
