import re, html
import httpx
import os

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# HTML 태그 제거용 정규식
TAG_RE = re.compile(r'<[^>]+>')

def clean_description(raw: str, word: str = '') -> str:
    # 1. HTML 제거 및 디코딩
    text = TAG_RE.sub('', raw)
    text = html.unescape(text)

    # 2. 단어 머리말 제거
    text = re.sub(rf'^{re.escape(word)}[\s:：\-–~]*(은|는|이|란|이란|이란 것은)?\s*', '', text, flags=re.IGNORECASE)

    # 3. 목차 번호 제거
    text = re.sub(r'\b\d+(\.\d+)*[\.\)]?\s*', '', text)
    text = re.sub(r'^[•▶\-–—·;\,\s]*', '', text)

    # 4. 괄호 제거
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\([^)]*\]', '', text)

    # 5. 문장 나누기 (영문 이니셜 보존)
    split_regex = r'(?<![A-Z])\.(?![A-Z])\s+|[?!…]\s+|\n+'
    candidates = re.split(split_regex, text.strip())

    # 6. 문장 선택 조건 완화
    for s in candidates:
        s = s.strip()
        # 조건: 한글 포함, 15자 이상, 마침표로 끝나거나 완결성 있는 문장
        if len(s) >= 15 and re.search(r'[가-힣]', s):
            return s if s.endswith('.') else s + '.'

    # 7. 대체 문장
    text = re.sub(r'\s+', ' ', text).strip()
    if text and not text.endswith('.'):
        text += '.'
    return text

async def get_naver_clue(query: str) -> str:
    url = "https://openapi.naver.com/v1/search/encyc.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": 1}

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers, params=params)
        if res.status_code == 200:
            items = res.json().get("items", [])
            if items:
                raw_description = items[0].get("description", "")
                return clean_description(raw_description)
    return ""
