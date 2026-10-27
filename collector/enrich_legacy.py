# 승인 장부(data.json)를 1단계 개편용 데이터로 변환한다.
# 원칙: 장부에 있는 값에서만 도출하고, 근거가 없으면 null(화면에서 '확인 필요')로 둔다.
import json, re, sys

src = json.load(open(sys.argv[1], encoding="utf-8"))
events = src["events"]

# 1) 공연초대 삭제: kind가 '공연 초대'이거나, 문화포털 공연 초대권이 '기타'로 분류된 건
def is_show(e):
    return e["kind"] == "공연 초대" or ("공연 초대권" in (e["prize"] or "") and "현장 관람" in e["tags"])

removed = [e for e in events if is_show(e)]
events = [e for e in events if not is_show(e)]

# 2) 플랫폼 판별: 원문 URL 도메인 + 장부 태그
def platforms(e):
    u = (e["url"] or "").lower()
    p = []
    if "instagram.com" in u or "인스타 참여" in e["tags"]: p.append("insta")
    if "youtube.com" in u or "youtu.be" in u or "유튜브 참여" in e["tags"]: p.append("yt")
    if "blog.naver.com" in u or "cafe.naver.com" in u: p.append("naver")
    if "x.com/" in u or "twitter.com" in u: p.append("x")
    if "t.me/" in u: p.append("tg")
    if "coupang.com" in u or "smartstore.naver.com" in u: p.append("shop")
    if not p: p.append("web")
    return p

# 장부 링크가 주최 원문이 아니라 이벤트 목록 사이트인 경우
def via_list(e):
    return "events.kr/" in (e["url"] or "")

# 3) 공공기관 판별: 기업·개인 주최를 명시 목록으로 빼고 나머지는 공공 주최로 본다
PRIVATE = ["BNK투자증권", "현대차증권", "한독 모터스", "씨게이트", "파리바게뜨", "신한라이프", "행복얼라이언스",
           "지냄", "옥시젠슈티컬스", "필로텍", "동서식품", "십세들", "주최 미표기"]
def is_public(e):
    return not any(k in (e["org"] or "") for k in PRIVATE)

# 4) 경품 종류: 경품 문구의 키워드로 분류(여러 개 가능)
PRIZE_TYPES = [
    ("coffee", ["커피", "아메리카노", "라떼", "스타벅스", "투썸", "메가", "컴포즈", "공차", "프라페", "밀크티"]),
    ("gift", ["상품권", "네이버페이", "포인트", "금액권", "해피콘", "배달의민족", "배민", "온누리", "튼튼머니", "땡겨요", "배달쿠폰", "기프티콘"]),
    ("food", ["치킨", "피자", "케이크", "디저트", "한우", "브리또"]),
    ("goods", ["워치", "에어팟", "고프로", "헤드셋", "카메라", "골드바", "숙박권", "퓨리케어", "크림", "키보드", "독서등",
               "캐리어", "테이블웨어", "초대권", "버즈", "굿즈", "레디백", "인스탁스"]),
]
def prize_types(e):
    p = e["prize"] or ""
    t = [k for k, words in PRIZE_TYPES if any(w in p for w in words)]
    return t

# 5) 확인된 경품 금액(원): 문구에 숫자 금액이 적힌 경우만, 1개 경품 기준 최댓값
def prize_value(e):
    p = (e["prize"] or "").replace(" ", "")
    vals = []
    for m in re.finditer(r"(\d+)만(\d)?천?원", p):
        vals.append(int(m.group(1)) * 10000 + (int(m.group(2)) * 1000 if m.group(2) else 0))
    for m in re.finditer(r"(?<![\d만])(\d+)천원", p):
        vals.append(int(m.group(1)) * 1000)
    for m in re.finditer(r"(\d{1,3}(?:,\d{3})+|\d{4,})원", p):
        vals.append(int(m.group(1).replace(",", "")))
    return max(vals) if vals else None

# 6) 제세공과금 가능성: 고가 실물 경품 키워드 또는 확인 금액 5만원 초과
TAX_WORDS = ["골드바", "워치", "에어팟", "고프로", "숙박권", "퓨리케어", "헤드셋", "카메라", "버즈", "한우", "캐리어"]
def tax_flag(e, v):
    p = e["prize"] or ""
    return any(w in p for w in TAX_WORDS) or (v is not None and v > 50000)

# 7) 예상 참여 시간 구간: 0=10초, 1=1분, 2=5분, 3=5분 이상, None=확인 필요
#    est=True 이면 장부의 절차·태그로 추정한 값
def time_bucket(e):
    if e["max"]:
        m = e["max"]
        return (1 if m <= 1 else 2 if m <= 5 else 3), False
    tags = e["tags"]
    if "10분 넘게 걸림" in tags or "아이디어 제출" in tags: return 3, False
    if "원문 미확인" in tags or "세부 미확인" in tags: return None, True
    if e["kind"] == "설문": return 3 if "10분" in " ".join(e["needs"]) else 2, True
    if "캡처 인증" in tags or "로그인 필요" in tags: return 2, True
    if e["kind"] in ("퀴즈", "투표"): return 2, True
    if e["kind"] == "댓글": return 1, True
    return None, True

# 8) 계정 필요 여부
def need_account(e):
    txt = " ".join(e["needs"] + e["steps"] + e["reasons"] + e["tags"])
    return bool(re.search(r"회원가입|로그인", txt))

def need_sns(e, plats):
    if any(p in plats for p in ("insta", "yt", "naver", "x", "tg")): return True
    txt = " ".join(e["needs"] + e["tags"] + e["reasons"])
    return bool(re.search(r"팔로우|구독|SNS|공유·게시형", txt))

# 9) 유료 조건 점검: 구매·결제·입금·참가비 문구가 있으면 검토 목록으로 출력(자동 게시 안 함)
PAY = re.compile(r"구매|결제|입금|참가비|유료|기부")
def pay_hits(e):
    txt = " ".join(e["needs"] + e["steps"] + [e["title"], e["prize"] or ""])
    return PAY.findall(txt)

# 사람이 원문을 보고 '유료 조건 아님'을 확인한 예외(장부 문구 근거)
PAY_OK = {
    "jjwf-kakao-together-cheer-share-2026": "기부는 필수가 아니라고 공지에 안내됨",
    "e169": "설문 1건당 주최 측이 매칭기부하는 방식으로, 참여자 결제 없음(목록 메모 기준)",
    "e184": "'기부니'는 이벤트 이름의 말장난이며 결제 조건 없음(목록 메모 기준). 4~9월 행복취향.ZIP 3건 이상 참여자 대상",
}

out, review = [], []
for e in events:
    plats = platforms(e)
    v = prize_value(e)
    tb, est = time_bucket(e)
    hits = pay_hits(e)
    if hits and e["id"] not in PAY_OK:
        review.append((e["id"], e["title"], hits))
        continue  # 무료 여부가 확인되지 않으면 게시하지 않는다
    unverified = "원문 미확인" in e["tags"] or via_list(e)
    pt = prize_types(e)
    e2 = dict(e)
    e2.update({
        "plats": plats,
        "pub": is_public(e),
        "viaList": via_list(e),
        "ptypes": pt,
        "value": v,
        "tax": tax_flag(e, v),
        "tb": tb, "est": est,
        "acct": need_account(e),
        "sns": need_sns(e, plats),
        # 무료 확인 상태: ok=장부상 유료 조건 없음, check=원문 미확인이라 무료 여부도 원문 확인 필요
        "free": "check" if unverified else "ok",
        "freeNote": PAY_OK.get(e["id"]),
    })
    out.append(e2)

meta = dict(src["meta"])
meta["removedShows"] = len(removed)
meta["shown"] = len(out)
json.dump({"meta": meta, "events": out}, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

# 검토용 보고서
with open(sys.argv[3], "w", encoding="utf-8") as r:
    print("삭제(공연초대):", len(removed), [x["id"] for x in removed], file=r)
    print("게시:", len(out), file=r)
    print("유료 의심으로 보류:", review, file=r)
    from collections import Counter
    print("플랫폼:", Counter(p for e in out for p in e["plats"]), file=r)
    print("목록사이트 경유:", sum(e["viaList"] for e in out), file=r)
    print("공공:", sum(e["pub"] for e in out), "민간:", [e["org"] for e in out if not e["pub"]], file=r)
    print("경품종류:", Counter(t for e in out for t in e["ptypes"]), "미분류:", [e["prize"] for e in out if not e["ptypes"]], file=r)
    print("시간:", Counter((e["tb"], e["est"]) for e in out), file=r)
    print("계정:", sum(e["acct"] for e in out), "SNS:", sum(e["sns"] for e in out), "세금:", [e["prize"][:30] for e in out if e["tax"]], file=r)
    print("무료확인:", Counter(e["free"] for e in out), file=r)
    for e in out:
        if e["value"]: print("  금액", e["value"], "|", e["prize"][:60], file=r)
