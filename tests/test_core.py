# 핵심 규칙 단위 테스트: python -m pytest tests (pytest가 없으면 python tests/test_core.py)
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.common import period, find_dates
from collector.extract import build_event, pay_required, is_show_invite, is_region_limited, norm_url
from collector import pipeline as P


def ev(title, url, end="2099-12-31", body="댓글 남기면 커피 기프티콘 10명 추첨", **kw):
    e, why = build_event(src="t", sid=url + title, title=title, url=url, body=body, end=dt.date.fromisoformat(end) if end else None, **kw)
    assert e, why
    return e


def test_period():
    assert period("2026. 10. 05.(월) ~ 10. 31.(토)") == (dt.date(2026, 10, 5), dt.date(2026, 10, 31))
    s, e = period("2026년 12월 20일 ~ 1월 5일")
    assert (s, e) == (dt.date(2026, 12, 20), dt.date(2027, 1, 5))
    assert find_dates("발표 11/4") == [dt.date(dt.date.today().year, 11, 4)]


def test_pay_filter():
    assert pay_required("제품 구매 후 리뷰 작성 시 증정")
    assert not pay_required("구매 없이 누구나 응모 가능, 추첨 증정")
    assert not pay_required("댓글 남기면 추첨")
    assert pay_required("상품 선결제 주문 후 리뷰 확인 완료 후 페이백 진행")  # 체험단 페이백형은 유료
    assert not pay_required("3만원 이용권 제공, 방문 후 블로그 리뷰")
    e, why = build_event(src="t", sid="1", title="구매 인증 이벤트", url="https://a.kr/1", body="3만원 이상 구매 고객 추첨")
    assert e is None and "유료" in why


def test_show_excluded():
    assert is_show_invite("연극 '알테르 에고' 초대 이벤트")
    assert is_show_invite("지브리 영화음악 콘서트 초대권 2장")
    assert not is_show_invite("아르코 공연 기대평으로 헤드셋 받자")
    assert not is_show_invite("특구 영상 댓글 CGV 영화관람권 20명")
    e, why = build_event(src="t", sid="2", title="문화초대이벤트 뮤지컬 관람권 증정", url="https://a.kr/2", body="추첨")
    assert e is None and why == "공연초대"


def test_region_limited():
    assert is_region_limited("연제구 지역주민 누구나")
    assert is_region_limited("서울시민 누구나 댓글")
    assert is_region_limited("태그 지역 한정")
    assert is_region_limited("서울 / 경기 / 인천 지역에서만 참여 가능합니다")
    assert is_region_limited("[창원 전 지역에서 참여 가능합니다] 체험단")
    assert is_region_limited("지역 초대 행사")
    assert not is_region_limited("인천시민 한정인지는 미확인. 정답을 맞힌 응모자 중 추첨")
    assert not is_region_limited("제주어에 관심 있는 누구나. 제주 거주 필수라고 안내하지 않음")
    assert not is_region_limited("전북 지역특산품 100명")
    assert not is_region_limited("친구 초대 인증하고 치킨 쿠폰")
    assert not is_region_limited("맥심 컵 한정판 세트")
    assert not is_region_limited("[서울/강남구] 오대양참치 체험단")
    assert not pay_required("구매하고 싶은 제품명 댓글")
    assert not pay_required("한국예탁결제원 유튜브 구독 후 댓글")
    assert pay_required("선결제 후 리뷰")
    e, why = build_event(src="t", sid="reg", title="연제구 지역주민 한정 댓글 이벤트", url="https://a.kr/reg", body="커피 기프티콘 추첨")
    assert e is None and why == "지역 한정"


def test_norm_url():
    assert norm_url("https://www.instagram.com/p/AbC/?hl=ko&img_index=1") == norm_url("https://instagram.com/p/AbC")
    assert norm_url("https://www.youtube.com/watch?v=x1&si=zz") == norm_url("https://youtube.com/watch?v=x1")
    assert norm_url("https://youtu.be/Cf4iatanjTw?si=1") == norm_url("https://www.youtube.com/watch?v=Cf4iatanjTw")


def test_dedupe_and_board_items_stay_separate():
    db = {"events": {}}
    st = {"added": 0, "merged": 0}
    a = ev("부산시보 다른그림 찾기", "https://busan.go.kr/EVTView?srchIdx=1")
    b = ev("독자 만족도조사 참여하고 기프티콘 받자", "https://busan.go.kr/EVTView?srchIdx=2")
    P.merge(db, a, "2026-10-27", st)
    P.merge(db, b, "2026-10-27", st)
    assert st == {"added": 2, "merged": 0}  # 같은 게시판의 다른 글은 합치지 않는다
    # 같은 원문 링크(추적 파라미터만 다름)는 하나로
    c = ev("다른 제목이어도", "https://www.busan.go.kr/EVTView?srchIdx=1&utm_source=x")
    assert P.merge(db, c, "2026-10-27", st) == a["id"] and st["merged"] == 1
    # 제목이 거의 같고 마감일이 같으면 하나로(모음 사이트에서 다시 발견)
    d = ev("[부산시] 부산시보 다른그림 찾기!", "https://events.kr/event.php?id=9")
    assert P.merge(db, d, "2026-10-27", st) == a["id"]
    # 제목이 같아도 마감일이 다르면 다른 회차
    e2 = ev("부산시보 다른그림 찾기", "https://busan.go.kr/EVTView?srchIdx=3", end="2099-11-30")
    assert P.merge(db, e2, "2026-10-27", st) != a["id"]


def test_similar_titles_from_different_orgs_stay_separate():
    db = {"events": {}}
    st = {"added": 0, "merged": 0}
    a = ev("퀴즈 풀고 커피 받자 이벤트!!", "https://a.kr/q1", org="서울시의회")
    b = ev("퀴즈 풀고 커피 받자 이벤트!!", "https://b.kr/q2", org="오븐마루치킨")
    c = ev("퀴즈 풀고 커피 받자 이벤트!!", "https://www.eventhouse.kr/site/view.php?no=1", org="서울특별시의회")
    assert P.merge(db, a, "2026-10-27", st) != P.merge(db, b, "2026-10-27", st)
    assert P.merge(db, c, "2026-10-27", st) == a["id"]  # 같은 주최(표기만 다름)는 합친다
    assert db["events"][a["id"]]["url"] == "https://a.kr/q1"  # 원문 링크가 대표로 남는다


def test_prize_value():
    from collector.enrich import prize_value
    cases = {"GS25 5천원권 500명": 5000, "배달의민족 5만원권 20명": 50000, "모바일 상품권 5,000원": 5000,
             "상품권 1만 원 50명": 10000, "온누리 1만5천원": 15000, "CU 모바일 금액권 5천원 1,000명": 5000, "커피 쿠폰": None}
    for p, v in cases.items():
        assert prize_value({"prize": p}) == v, p


def test_aggregator_prize_tidy():
    from collector.sources.aggregators import tidy_prize, numbered
    assert tidy_prize("GS25 모바일상품권 5천원권-20명") == "GS25 모바일상품권 5천원권 20명"
    assert tidy_prize("네이버페이-00명") == "네이버페이"  # 사이트가 가린 인원은 지운다
    assert tidy_prize("상품-200명") == "상품 200명"
    assert numbered("① 팔로우 ② 댓글") == ["1. 팔로우", "2. 댓글"]


def test_audit():
    db = {"events": {}}
    st = {"added": 0, "merged": 0}
    a = ev("SNS 팔로우하고 아메리카노 챙기자 이벤트!!", "https://a.kr/1", end="2026-10-28", org="전북특별자치도")
    b = ev("SNS 팔로우하고 아메리카노 챙기자 이벤트!!", "https://b.kr/2", end="2026-10-28", org="전북시")
    c = ev("퀴즈 맞히고 치킨세트 받아가자 이벤트", "https://c.kr/3", end="2027-08-31", org="치킨")
    d = ev("댓글 이벤트", "https://d.kr/4", end="2026-11-30", org="몰")
    for x in (a, b, c, d):
        db["events"][x["id"]] = dict(x, status="active")
    db["events"][d["id"]]["steps"] = ["상품 선결제 후 리뷰 확인되면 페이백"]  # 수집 뒤에 규칙이 강화된 경우
    db["events"][a["id"]]["linkStatus"] = "error SSLError"
    r = P.audit(db, "2026-10-27")
    assert db["events"][d["id"]]["status"] == "excluded"
    assert db["events"][c["id"]]["issues"] == ["마감일"]
    assert db["events"][a["id"]]["issues"] == ["원문 링크 접속"]
    assert [db["events"][x["id"]]["status"] for x in (a, b)].count("merged") == 1
    assert r == {"excluded": 1, "flagged": 2, "merged": 1}
    P.update_status(db, "2026-10-27", {})  # 종료 처리가 제외·병합 상태를 되돌리지 않는다
    assert db["events"][d["id"]]["status"] == "excluded"


def test_status_expiry():
    db = {"events": {}}
    st = {"added": 0, "merged": 0}
    old = ev("지난 이벤트", "https://a.kr/old", end="2026-10-20")
    noend = ev("2026년 9월 퀴즈 이벤트", "https://a.kr/m", end=None)
    live = ev("진행 이벤트", "https://a.kr/live", end="2026-11-30")
    due = ev("오늘 마감 퀴즈", "https://a.kr/tod", end="2026-10-27")
    for x in (old, noend, live, due):
        P.merge(db, x, "2026-10-27", st)
    db["events"]["region"] = {"id": "region", "title": "마음건강 댓글", "url": "https://a.kr/region", "status": "active",
                               "end": "2026-11-30", "who": "연제구 지역주민 누구나", "tags": ["지역 한정"], "needs": [],
                               "prize": "스타벅스", "kind": "댓글", "steps": []}
    db["events"]["show"] = {"id": "show", "title": "뮤지컬 관람 초대", "url": "https://a.kr/show", "status": "active",
                             "end": "2026-11-30", "prize": "뮤지컬 초대권", "kind": "기타", "tags": [], "needs": [], "steps": [], "who": None}
    P.update_status(db, "2026-10-27", {})
    s = {e["title"]: e["status"] for e in db["events"].values()}
    assert "지난 이벤트" not in s and "2026년 9월 퀴즈 이벤트" not in s
    assert "마음건강 댓글" not in s and "뮤지컬 관람 초대" not in s
    assert s == {"진행 이벤트": "active", "오늘 마감 퀴즈": "active"}


def test_bot_events_select():
    from collector.bot_events import canonical_record, select_events, to_event
    today = "2026-10-28"
    assert to_event({"title": "끝난 행사 이벤트", "url": "https://a.kr/z", "deadline": "2026-10-27", "prize": "커피 기프티콘", "how_to_enter": "댓글"}, today) is None
    assert to_event({"title": "지역 주민 한정 댓글 이벤트", "url": "https://a.kr/r", "deadline": "2026-11-01", "prize": "커피", "how_to_enter": "지역주민만 참여"}, today) is None
    note = canonical_record({"title": "경남 영상 댓글 이벤트", "url": "https://youtu.be/Oif8TA4Go6Y", "deadline": "2026-11-05",
                              "prize": "네이버페이 1만원 10명", "how_to_enter": "영상 설명란 참여방법 확인→댓글(지역 한정이면 건너뜀)"})
    assert note and "건너뜀" not in note["how_to_enter"] and note["platform"] == "YouTube"
    kept = select_events([
        {"title": "[한국석유공사] 퀴즈 이벤트", "url": "https://youtu.be/abcdefghijk", "deadline": "2026-10-28", "platform": "YouTube", "prize": "네이버페이 1만원 20명", "how_to_enter": "구독 후 정답 댓글"},
        {"name": "새 설문 이벤트", "entry_url": "https://forms.gle/abcDEF123", "deadline": "2026-11-02", "prize": "커피 기프티콘 10명", "steps": "① 설문 응답 ② 제출", "verified_source": "suto.co.kr/cpevent/1"},
        {"title": "구매하고 싶은 제품 댓글 이벤트", "url": "https://www.youtube.com/watch?v=zzzzzzzzzzz", "deadline": "2026-11-02", "prize": "네이버페이 5천원 5명", "how_to_enter": "좋아요→구매하고 싶은 제품명 댓글"},
    ], [{"id": "x", "title": "퀴즈 이벤트", "url": "https://www.youtube.com/watch?v=abcdefghijk&si=1", "end": "2026-10-28", "org": "한국석유공사", "status": "active", "srcUrls": []}], today)
    titles = {e["title"] for e in kept}
    assert "퀴즈 이벤트" not in titles  # 같은 영상 주소
    assert any(e["src"] == "pp" and e["bot"] and e["kind"] == "설문" for e in kept)
    assert any("구매하고 싶은" in e["title"] for e in kept)


def test_safety_abort(tmp_path, monkeypatch):
    # 진행 중 건수가 절반 아래로 줄면 db.json을 쓰지 않고 2를 돌려준다
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "CONFIG", tmp_path / "none.json")
    monkeypatch.setattr(P, "SOURCES", {})
    events = {f"x{i}": {"id": f"x{i}", "title": f"t{i}", "url": f"https://a.kr/{i}", "status": "active",
                        "end": "2026-10-01" if i < 30 else "2099-01-01", "tags": [], "reasons": []} for i in range(40)}
    P.dump(tmp_path / "db.json", {"events": events})
    before = (tmp_path / "db.json").read_text(encoding="utf-8")
    assert P.main(["--force", "--no-links"]) == 2
    assert (tmp_path / "db.json").read_text(encoding="utf-8") == before


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
