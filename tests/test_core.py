# 핵심 규칙 단위 테스트: python -m pytest tests (pytest가 없으면 python tests/test_core.py)
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.common import period, find_dates
from collector.extract import build_event, pay_required, is_show_invite, norm_url
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
    e, why = build_event(src="t", sid="2", title="문화초대이벤트 뮤지컬 관람권 증정", url="https://a.kr/2", body="추첨")
    assert e is None and why == "공연초대"


def test_norm_url():
    assert norm_url("https://www.instagram.com/p/AbC/?hl=ko&img_index=1") == norm_url("https://instagram.com/p/AbC")
    assert norm_url("https://www.youtube.com/watch?v=x1&si=zz") == norm_url("https://youtube.com/watch?v=x1")


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


def test_status_expiry():
    db = {"events": {}}
    st = {"added": 0, "merged": 0}
    old = ev("지난 이벤트", "https://a.kr/old", end="2026-10-20")
    noend = ev("2026년 9월 퀴즈 이벤트", "https://a.kr/m", end=None)
    live = ev("진행 이벤트", "https://a.kr/live", end="2026-11-30")
    for x in (old, noend, live):
        P.merge(db, x, "2026-10-27", st)
    P.update_status(db, "2026-10-27", {})
    s = {e["title"]: e["status"] for e in db["events"].values()}
    assert s == {"지난 이벤트": "ended", "2026년 9월 퀴즈 이벤트": "ended", "진행 이벤트": "active"}


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
