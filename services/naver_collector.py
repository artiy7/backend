import httpx
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()
CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

HEADERS = {
    "X-Naver-Client-Id": CLIENT_ID,
    "X-Naver-Client-Secret": CLIENT_SECRET,
}
NAVER_URL = "https://openapi.naver.com/v1/search/encyc.json"

WHITELIST_SOURCES = ["백과", "사전", "두산", "브리태니커", "시사"]

async def search_topic(query: str, display=100):
    params = {
        "query": query,
        "display": display,
        "start": 1,
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(NAVER_URL, headers=HEADERS, params=params)
        data = res.json()
        items = data.get("items", [])

        print(f"📦 총 응답 항목 수: {len(items)}")

        filtered = []
        for item in items:
            maker = item.get("maker", "")
            print(f"🔍 maker: {maker}")  # 디버깅 출력

            if any(keyword in maker for keyword in WHITELIST_SOURCES):
                filtered.append({
                    "word": BeautifulSoup(item["title"], "html.parser").text,
                    "definition": BeautifulSoup(item["description"], "html.parser").text,
                    "maker": maker,
                })

        print(f"✅ 필터링 후 결과 수: {len(filtered)}")
        return filtered

# 단독 실행
if __name__ == "__main__":
    import asyncio
    topic = input("검색할 주제를 입력하세요 (예: 수학): ")
    results = asyncio.run(search_topic(topic))

    print(f"\n🔍 최종 출력 결과\n")
    for item in results:
        print(f"🟢 {item['word']} ({item['maker']})")
        print(f"→ {item['definition']}\n")
