import asyncio
import re, requests

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

def preprocess_word(word: str) -> str:
    """URL에 들어가기 적절하도록 전처리"""
    return word.strip().replace(" ", "_")

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