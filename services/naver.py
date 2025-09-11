import httpx
import os
from dotenv import load_dotenv

load_dotenv()
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

async def search_encyclopedia(query: str):
    url = "https://openapi.naver.com/v1/search/encyc.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": 10,
        "start": 1,
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers, params=params)
        return res.json()
