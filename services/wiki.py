from fastapi import APIRouter, Query
import requests

router = APIRouter()

@router.get("/debug/topic-terms")
def get_topic_terms(topic: str):
    TOPIC_CATEGORIES = {
        "과학": ["물리학", "화학", "생물학", "천문학", "지구과학"],
        "사회": ["사회학", "정치학", "경제학", "법학", "역사", "지리학", "사회과학"],
        "수학": ["수학", "대수학", "기하학", "통계학", "수학사"],
        "국어": ["문학", "국어학", "한자", "어휘", "문법", "수사학"],
    }

    categories = TOPIC_CATEGORIES.get(topic)
    if not categories:
        return []

    EXCLUDE_KEYWORDS = ['개요', '목록', '역사', '분류', '문서']
    MAX_LEN = 7
    all_titles = set()

    for category in categories:
        url = "https://ko.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"분류:{category}",
            "format": "json",
            "cmlimit": 500
        }
        headers = {
            "User-Agent": "CrosswordPuzzleBot/1.0 (https://myapp.local/)"
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"❌ {category} 요청 실패: {e}")
            continue  # 다음 카테고리로 진행

        for item in data.get("query", {}).get("categorymembers", []):
            title = item["title"]
            if ":" in title:
                continue
            if "(" in title:
                continue
            if " " in title:
                continue
            if any(k in title for k in EXCLUDE_KEYWORDS):
                continue
            if any(c.isascii() and c.isalpha() for c in title):
                continue
            if 1 <= len(title) <= MAX_LEN:
                all_titles.add(title)

    return sorted(all_titles)