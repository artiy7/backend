from asyncio import Queue, TimeoutError, wait_for
from services.puzzle_generator import generate_random_puzzle_for_match
from starlette.websockets import WebSocket, WebSocketState
import asyncio, datetime
from db import db

TIER_SCORE = {
        "브론즈": 500,
        "실버": 1250,
        "골드": 2000,
        "다이아": 2750,
        "신화": 3500,
        "전설": 4250,
        "마스터": 5000
    }

def calculate_score_change(winner_tier: str, loser_tier: str) -> tuple[int, int]:


    winner_base = TIER_SCORE.get(winner_tier, 0)
    loser_base = TIER_SCORE.get(loser_tier, 0)

    if not isinstance(winner_base, int) or not isinstance(loser_base, int):
        print(f"❌ 잘못된 티어: winner={winner_tier}, loser={loser_tier}")
        return 0, 0

    gap = abs(winner_base - loser_base)

    # 최대 보너스 100점, 최대 점수차 1250점
    base_gain = 200
    bonus = int((gap / 1250) * 100)
    bonus = min(bonus, 100)

    gain = base_gain + bonus
    loss = int(gain * 0.5)

    return gain, loss

def calculate_tier(score: int) -> str:
    if score >= 5000:
        return "마스터"
    if score >= 4250:
        return "전설"
    elif score >= 3500:
        return "신화"
    elif score >= 2750:
        return "다이아"
    elif score >= 2000:
        return "골드"
    elif score >= 1250:
        return "실버"
    elif score >= 500:
        return "브론즈"
    else:
        return "없음"
    
def determine_tier(score: int) -> str:
    for tier, tier_score in reversed(TIER_SCORE.items()):
        if score >= tier_score:
            return tier
    return "없음"

async def update_user_tier(email: str):
    user_col = db["users"]
    user = await user_col.find_one({"email": email})
    if not user:
        print(f"❌ 티어 업데이트 실패: {email} 유저 없음")
        return

    score = user.get("score", 0)
    new_tier = determine_tier(score)

    if new_tier != user.get("tier"):
        await user_col.update_one(
            {"email": email},
            {"$set": {"tier": new_tier}}
        )
        print(f"🎉 티어 갱신됨: {email} → {new_tier}")
    
async def apply_match_result(winner_email: str, loser_email: str, topic: str):
    user_col = db["users"]

    winner = await user_col.find_one({"email": winner_email})
    loser = await user_col.find_one({"email": loser_email})

    if not winner or not loser:
        print("❌ 유저 정보 조회 실패")
        return

    winner_tier = winner.get("tier")
    loser_tier = loser.get("tier")
    gain, loss = calculate_score_change(winner_tier, loser_tier)
    print(f"✅ {winner_email} +{gain} / {loser_email} -{loss}")

    # 승리자 점수 증가
    await user_col.update_one(
        {"email": winner_email},
        {"$inc": {"score": gain}}
    )

    # 패배자 점수 감소 (0점 미만 방지)
    new_loser_score = loser.get("score", 0) - loss
    if new_loser_score < 0:
        new_loser_score = 0

    await user_col.update_one(
        {"email": loser_email},
        {"$set": {"score": new_loser_score}}
    )
    
    # 점수 업데이트 후 현재 점수 재조회
    updated_winner = await user_col.find_one({"email": winner_email})
    updated_loser = await user_col.find_one({"email": loser_email})

    new_winner_tier = calculate_tier(updated_winner.get("score", 0))
    new_loser_tier = calculate_tier(updated_loser.get("score", 0))
    
    await user_col.update_one(
        {"email": winner_email},
        {"$set": {"tier": new_winner_tier}}
    )

    await user_col.update_one(
        {"email": loser_email},
        {"$set": {"tier": new_loser_tier}}
    )
    await update_user_tier(winner_email)
    await update_user_tier(loser_email)

    await db["users"].update_one(
        {"email": winner_email},
        {"$inc": {f"win_rate.{topic}.win": 1}}
    )

    # ✅ 2. 패자 패배 기록 증가
    await db["users"].update_one(
        {"email": loser_email},
        {"$inc": {f"win_rate.{topic}.lose": 1}}
    )
    
    print(f"🏅 승자 티어 업데이트: {winner_email} → {new_winner_tier}")
    print(f"🏅 패자 티어 업데이트: {loser_email} → {new_loser_tier}")
    
async def update_win_rate(email: str, topic: str, is_win: bool):
    user_col = db["users"]
    field = f"win_rate.{topic}.win" if is_win else f"win_rate.{topic}.lose"
    await user_col.update_one({"email": email}, {"$inc": {field: 1}})
    
class MatchPlayer:
    def __init__(self, websocket: WebSocket, tier: str):
        self.websocket = websocket
        self.tier = tier
        

class MatchManager:
    def __init__(self):
        self.queue = Queue()
        self.active_matches = {}
        self.user_emails = {}
        self.finished_clients = set()

    async def _is_socket_alive(self, ws: WebSocket, label="unknown"):
        if ws.client_state != WebSocketState.CONNECTED:
            print(f"❌ {label} client_state = CLOSED (ping 안함)")
            return False
        try:
            await ws.send_json({"type": "ping"})
            print(f"✅ {label} ping 성공")
            return True
        except Exception as e:
            print(f"❌ {label} ping 실패:", e)
            return False

    async def enqueue(self, websocket: WebSocket):
        # 이미 큐에 있는 소켓인지 확인
        for player in list(self.queue._queue):
            if player.websocket.client == websocket.client:
                print("⚠️ 이미 큐에 존재하는 소켓입니다. enqueue 중단.")
                return

        print("💣 ENQUEUE 들어옴:", datetime.datetime.now())

        try:
            await websocket.send_json({"type": "request_tier"})
            data = await wait_for(websocket.receive_json(), timeout=5)
            print("✅ tier 수신:", data, "from", websocket.client)

            if data.get("type") != "tier" or not data.get("value"):
                await websocket.close()
                return

            tier = data.get("value")
            email = data.get("email")
            
            if not email:
                await websocket.close()
                return
            
            self.user_emails[websocket] = email
            player = MatchPlayer(websocket, tier)

            if websocket.application_state != WebSocketState.CONNECTED:
                print("❌ 연결 종료 상태 → 큐에 넣지 않음")
                await websocket.close()
                return
            await self._remove_from_queue(websocket, None)
            await self.queue.put(player)
            print(f"📥 큐에 추가됨 (현재 큐 크기: {self.queue.qsize()})")

            await self.try_match_all()

        except Exception as e:
            print("❌ enqueue 에러:", e)
            try:
                await websocket.close()
            except:
                pass

        await self.wait_forever(websocket)

    async def try_match_all(self):
        temp_list = []
        while not self.queue.empty():
            player = await self.queue.get()
            if player.websocket.application_state == WebSocketState.CONNECTED:
                temp_list.append(player)
            else:
                print("🧹 끊긴 소켓을 큐에서 제거:", player.websocket.client)

        matched = set()
        for i in range(len(temp_list)):
            if i in matched:
                continue
            for j in range(i + 1, len(temp_list)):
                if j in matched:
                    continue

                p1, p2 = temp_list[i], temp_list[j]

                if not await self._is_socket_alive(p1.websocket, "p1") or not await self._is_socket_alive(p2.websocket, "p2"):
                    continue

                if not self._is_acceptable_match(p1.tier, p2.tier):
                    continue

                await p1.websocket.send_json({"type": "opponent_found"})
                await p2.websocket.send_json({"type": "opponent_found"})
                print("🧩 퍼즐 생성 중...")
                puzzle = await generate_random_puzzle_for_match()
                if "_id" in puzzle:
                    puzzle["_id"] = str(puzzle["_id"])
                print("✅ 퍼즐 생성 완료, 전송 시작")
                self.active_matches[p1.websocket] = p2.websocket
                self.active_matches[p2.websocket] = p1.websocket
                await self.safe_send_to_both(p1.websocket, p2.websocket, puzzle)

                matched.add(i)
                matched.add(j)
                break

        for idx, player in enumerate(temp_list):
            if idx not in matched:
                await self.queue.put(player)

    async def wait_forever(self, websocket):
        try:
            while websocket.application_state == WebSocketState.CONNECTED:
                try:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=15)
                    if data.get("type") == "ping":
                        try:
                            await websocket.send_json({"type": "pong"})
                            print(f"✅ ping 응답: {websocket.client}")
                        except Exception as e:
                            print("❌ ping 응답 실패:", e)
                        continue  # 다음 루프로 넘어감
                    elif data.get("type") == "leave_queue":
                        print("👋 큐에서 나감 요청 수신")

                        try:
                            new_queue = asyncio.Queue()
                            while not self.queue.empty():
                                player = await self.queue.get()
                                if player.websocket != websocket:
                                    await new_queue.put(player)
                            self.queue = new_queue
                            print("🧹 큐에서 사용자 제거 완료")
                        except Exception as e:
                            print("❌ 큐 제거 중 오류:", e)

                        await websocket.close()
                        return

                    elif data.get("type") == "leave":
                        print("👋 클라이언트가 자발적으로 나감 → 연결 종료 처리")
                        await self._handle_disconnect(websocket)
                        break
                    
                    elif data.get("type") == "win":
                        print("🏆 승리 메시지 수신:", websocket.client, data)
                        partner_ws = self.active_matches.get(websocket)
                        
                        winner_email = data.get("email")  # 프론트에서 보낸 사용자 이메일
                        loser_email = self.user_emails.get(partner_ws) if partner_ws else None     

                        if winner_email and loser_email:
                            # 점수 변화량 계산
                            winner = await db["users"].find_one({"email": winner_email})
                            loser = await db["users"].find_one({"email": loser_email})

                            winner_score = winner.get("socre", 0)
                            loser_score = loser.get("socre", 0)
                            
                            winner_tier = winner.get("tier", "브론즈")
                            loser_tier = loser.get("tier", "브론즈")
                            gain, loss = calculate_score_change(winner_tier, loser_tier)

                            print(f"✅ 점수 변화량: {winner_email} +{gain} / {loser_email} -{loss}")

                            # 실제 점수 업데이트
                            topic = data.get("topic", "과학")
                            await apply_match_result(winner_email, loser_email, topic)
                            
                            updated_winner = await db["users"].find_one({"email": winner_email})
                            new_winner_score = updated_winner.get("score", 0)
                            new_winner_tier = updated_winner.get("tier", "없음")
                            
                            updated_loser = await db["users"].find_one({"email": loser_email})
                            new_loser_score = updated_loser.get("score", 0)
                            new_loser_tier = updated_loser.get("tier", "없음")
                            # 패자에게 패배 메시지 전송
                            if partner_ws and partner_ws.application_state == WebSocketState.CONNECTED:
                                try:
                                    await partner_ws.send_json({
                                        "type": "end",
                                        "result": "lose",
                                        "score_change": -loss,
                                        "updated_score": new_loser_score,
                                        "updated_tier": new_loser_tier,
                                        "prev_score": winner_score,
                                        "reason": "상대방이 먼저 퍼즐을 완료했습니다.",
                                        "winner_time": data.get("time"),
                                        "partner_email": winner_email
                                    })
                                except Exception as e:
                                    print("❌ 패배 전송 실패:", e)

                            # 승자에게 승리 메시지 전송
                            try:
                                await websocket.send_json({
                                    "type": "end",
                                    "result": "win",
                                    "score_change": gain,
                                    "updated_score": new_winner_score,
                                    "updated_tier": new_winner_tier,
                                    "prev_score": winner_score,
                                    "reason": "축하합니다! 퍼즐을 완료했습니다.",
                                    "your_time": data.get("time"),
                                    "partner_email": loser_email
                                    
                                })
                            except Exception as e:
                                print("❌ 승리 전송 실패:", e)
                                
                    elif data.get("type") == "lose":
                        print("🏆 승리 메시지 수신:", websocket.client, data)
                        partner_ws = self.active_matches.get(websocket)
                        
                        loser_email = data.get("email")  # 프론트에서 보낸 사용자 이메일
                        winner_email = self.user_emails.get(partner_ws) if partner_ws else None     

                        if winner_email and loser_email:
                            # 점수 변화량 계산
                            winner = await db["users"].find_one({"email": winner_email})
                            loser = await db["users"].find_one({"email": loser_email})

                            winner_score = winner.get("socre", 0)
                            loser_score = loser.get("socre", 0)
                            
                            winner_tier = winner.get("tier", "브론즈")
                            loser_tier = loser.get("tier", "브론즈")
                            gain, loss = calculate_score_change(winner_tier, loser_tier)

                            print(f"✅ 점수 변화량: {winner_email} +{gain} / {loser_email} -{loss}")

                            # 실제 점수 업데이트
                            topic = data.get("topic", "과학")
                            await apply_match_result(winner_email, loser_email, topic)
                            
                            updated_winner = await db["users"].find_one({"email": winner_email})
                            new_winner_score = updated_winner.get("score", 0)
                            new_winner_tier = updated_winner.get("tier", "없음")
                            
                            updated_loser = await db["users"].find_one({"email": loser_email})
                            new_loser_score = updated_loser.get("score", 0)
                            new_loser_tier = updated_loser.get("tier", "없음")
                            # 패자에게 패배 메시지 전송
                            if partner_ws and partner_ws.application_state == WebSocketState.CONNECTED:
                                try:
                                    await websocket.send_json({
                                        "type": "end",
                                        "result": "lose",
                                        "score_change": -loss,
                                        "updated_score": new_loser_score,
                                        "updated_tier": new_loser_tier,
                                        "prev_score": loser_score,
                                        "reason": "포기했습니다.",
                                        "winner_time": data.get("time"),
                                        "partner_email": winner_email
                                        
                                    })

                                except Exception as e:
                                    print("❌ 패배 전송 실패:", e)

                            # 승자에게 승리 메시지 전송
                                try:
                                    await partner_ws.send_json({
                                        "type": "end",
                                        "result": "win",
                                        "score_change": gain,
                                        "updated_score": new_winner_score,
                                        "updated_tier": new_winner_tier,
                                        "prev_score": winner_score,
                                        "reason": "상대가 포기했습니다.",
                                        "your_time": data.get("time"),
                                        "partner_email": loser_email
                                    })                                

                                except Exception as e:
                                    print("❌ 승리 전송 실패:", e)

                        # 연결 종료 및 상태 초기화
                        await websocket.close()
                        if partner_ws:
                            await partner_ws.close()

                        self.active_matches.pop(websocket, None)
                        self.active_matches.pop(partner_ws, None)
                        self.user_emails.pop(websocket, None)
                        self.user_emails.pop(partner_ws, None)
                        return

                except asyncio.TimeoutError:
                    print("⏱️ 15초 응답 없음 → 연결 끊김 처리 시작")
                    await self._handle_disconnect(websocket)
                    break
                
                except Exception as e:
                    if str(e).startswith("(1000") or str(e).startswith("(1001"):
                        print("✅ 정상 종료로 인한 예외 무시:", e)
                        break
                    print("❌ WebSocket 수신 오류:", e)
                    await self._handle_disconnect(websocket)
                    break

        except Exception as e:
            print("❌ WebSocket 연결 끊김:", e)
            await self._handle_disconnect(websocket)

    async def safe_send_to_both(self, ws1, ws2, puzzle):
        print("📦 퍼즐 전송 시도")
        try:
            await ws1.send_json({"type": "start", "puzzle": puzzle})
        except Exception as e:
            print("❌ ws1 전송 실패:", e)
            try: await self._handle_disconnect(ws1)
            except: pass
            try: await self._handle_disconnect(ws2)
            except: pass
            return
        try:
            await ws2.send_json({"type": "start", "puzzle": puzzle})
        except Exception as e:
            print("❌ ws2 전송 실패:", e)
            try: await self._handle_disconnect(ws1)
            except: pass
            try: await self._handle_disconnect(ws2)
            except: pass

    async def _handle_disconnect(self, disconnected_ws: WebSocket):
        print("🔌 연결 끊김 감지:", disconnected_ws.client)

        # 디버그 로그 추가
        print("📌 현재 매칭 상태 keys:", list(self.active_matches.keys()))

        partner_ws = self.active_matches.get(disconnected_ws)
        if not partner_ws:
            print("ℹ️ 매치되지 않은 상태에서 연결 종료 (큐에만 있던 사용자)")
        print("🎯 파트너 웹소켓:", partner_ws)

        if partner_ws and partner_ws.application_state == WebSocketState.CONNECTED:
            winner_email = self.user_emails.get(partner_ws)
            loser_email = self.user_emails.get(disconnected_ws)
            if winner_email and loser_email:
                topic = "과학"  # 기본값 또는 상대방이 보낸 마지막 topic이 있다면 활용 가능
                print(f"📈 연결 끊김 → 자동 승자 처리: {winner_email} / 패자: {loser_email}")
                await apply_match_result(winner_email, loser_email, topic)

                updated_winner = await db["users"].find_one({"email": winner_email})
                new_winner_score = updated_winner.get("score", 0)
                new_winner_tier = updated_winner.get("tier", "없음")

                updated_loser = await db["users"].find_one({"email": loser_email})
                new_loser_score = updated_loser.get("score", 0)
                new_loser_tier = updated_loser.get("tier", "없음")

                gain, loss = calculate_score_change(
                    updated_winner.get("tier", "브론즈"),
                    updated_loser.get("tier", "브론즈")
                )

                # 승자에게 전송
                try:
                    await partner_ws.send_json({
                        "type": "end",
                        "result": "win",
                        "score_change": gain,
                        "updated_score": new_winner_score,
                        "updated_tier": new_winner_tier,
                        "prev_score": new_winner_score - gain,
                        "reason": "상대방이 나갔습니다. 승리 처리되었습니다.",
                        "your_time": -1,
                        "partner_email": loser_email
                    })
                except Exception as e:
                    print("⚠️ 자동승리 전송 실패:", e)

        try: await disconnected_ws.close()
        except: pass
        try: await partner_ws.close()
        except: pass

        self.active_matches.pop(disconnected_ws, None)
        if partner_ws:
            self.active_matches.pop(partner_ws, None)

        # 이메일 매핑 정리
        self.user_emails.pop(disconnected_ws, None)
        if partner_ws:
            self.user_emails.pop(partner_ws, None)

        # 혹시 큐에 남았을 수도 있으니 방어적으로 제거
        await self._remove_from_queue(disconnected_ws, None)
        if partner_ws:
            await self._remove_from_queue(partner_ws, None)
        
    async def force_leave_by_email(self, email: str):
        """HTTP 폴백: 이 이메일 유저가 떠났다고 가정하고 매치/큐를 정리"""
        print(f"🛎️ force_leave_by_email: {email}")
        target_ws = None

        # 1) 현재 연결된 소켓 찾기
        for ws, em in list(self.user_emails.items()):
            if em == email:
                target_ws = ws
                break

        # 2) 매치 중이면 _handle_disconnect 호출(상대에게 end 전송 포함)
        if target_ws and target_ws in self.active_matches:
            await self._handle_disconnect(target_ws)
            # _handle_disconnect 안에서 active_matches 정리 + 상대에게 end 전송 + close 수행
            return {"ok": True, "mode": "active"}

        # 3) 매치 중이 아니면 대기열에서 제거 후 소켓 닫기
        if target_ws:
            await self._remove_from_queue(target_ws, None)
            try:
                await target_ws.close()
            except:
                pass
            # 남은 매핑 정리
            self.user_emails.pop(target_ws, None)
            print("✅ 폴백: 대기열에서 제거 및 소켓 종료")
            return {"ok": True, "mode": "queued"}

        # 4) 소켓 자체를 못 찾았으면(이미 브라우저/네트워크에서 끊겼거나 재연결됨)
        #    대기열에서 이메일 기준으로라도 정리
        await self._remove_from_queue(None, email)
        print("ℹ️ 활성 소켓 없음: 큐만 정리")
        return {"ok": True, "mode": "none"}
        
    async def _remove_from_queue(self, target_ws: WebSocket | None = None, email: str | None = None):
        """대기열에서 해당 소켓/이메일을 제거"""
        try:
            new_queue = asyncio.Queue()
            while not self.queue.empty():
                player = await self.queue.get()
                keep = True
                if target_ws and player.websocket == target_ws:
                    keep = False
                if email and self.user_emails.get(player.websocket) == email:
                    keep = False
                if keep:
                    await new_queue.put(player)
            self.queue = new_queue
        except Exception as e:
            print("❌ _remove_from_queue 오류:", e)

    def _is_acceptable_match(self, t1, t2):
        tiers = ["없음", "브론즈", "실버", "골드", "다이아", "신화", "전설", "마스터"]
        try:
            return abs(tiers.index(t1) - tiers.index(t2)) <= 2  
        except:
            return False
