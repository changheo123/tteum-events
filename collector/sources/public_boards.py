# 공공기관 이벤트 게시판: 부산 이벤트 통합안내, 보건복지부 국민참여이벤트, 관광e배움터
import re

from ..common import text_of, find_dates, period, clean
from ..extract import build_event, ENDED


# ---- 부산민원120 이벤트(목록 표에 상태·대상·기간·발표가 모두 있음) ----
BUSAN = "https://www.busan.go.kr/minwon/eventresult"


def busan(f, state, cfg):
    d = f.doc(BUSAN)
    events, skipped, seen = [], {}, []
    for tr in d.xpath("//table//tr[td]"):
        tds = [text_of(td) for td in tr.xpath("./td")]
        a = tr.xpath(".//a[contains(@href,'EVTView')]")
        if len(tds) < 6 or not a:
            continue
        status, target, title, when, ann = tds[1], tds[2], clean(a[0].text_content()), tds[4], tds[5]
        if "진행" not in status:
            continue
        dates = find_dates(when)
        start, end = (dates[0], dates[1]) if len(dates) >= 2 else (None, None)
        ad = find_dates(ann)
        href = a[0].get("href")
        sid = re.search(r"srchIdx=(\d+)|prgcode=(\w+)", href)
        ev, why = build_event(
            src="bs", sid=(sid.group(1) or sid.group(2)) if sid else href, title=title, url=href,
            org="부산광역시", body=title + " 이벤트", start=start, end=end, announce=ad[0] if ad else None,
            extra_tags=["로그인 필요"] if "회원" in target else [])
        if ev:
            ev["who"] = None if target == "모두" else f"부산시 누리집 {target} 대상"
            events.append(ev)
            seen.append(ev["id"])
        else:
            skipped[title] = why
    return {"events": events, "seen": seen, "listed": len(events) + len(skipped), "skipped": skipped}


# ---- 보건복지부 국민참여이벤트(산하기관 이벤트 모음) ----
MOHW = "https://www.mohw.go.kr/gallery.es?mid=a10314000000&bid=0015"


def mohw(f, state, cfg):
    st = state.setdefault("mohw", {"parsed": {}})
    d = f.doc(MOHW)
    links = {}
    for a in d.xpath("//a[contains(@href,'act=view') and contains(@href,'list_no=')]"):
        no = re.search(r"list_no=(\d+)", a.get("href")).group(1)
        links.setdefault(no, f"{MOHW}&act=view&list_no={no}")
    events, skipped, budget = [], {}, cfg.get("max_details", 15)
    for no, url in links.items():
        if no in st["parsed"] or budget <= 0:
            continue
        budget -= 1
        try:
            v = f.doc(url)
        except Exception as e:
            skipped[no] = f"오류: {e}"[:120]
            continue
        lines = text_of(v.xpath("//body")[0]).splitlines()
        title_line = next((x for x in lines if x.startswith("[") and "]" in x and "<" not in x), None)
        if not title_line:
            st["parsed"][no] = "skip:제목 없음"
            continue
        org = re.match(r"\[([^\]]+)\]", title_line).group(1)
        title = re.sub(r"^\[[^\]]+\]\s*", "", title_line)
        when = next((x for x in lines if x.startswith("행사일")), "")
        ds = find_dates(when)
        try:
            k = lines.index(title_line, lines.index(title_line) + 1)
        except ValueError:
            k = lines.index(title_line)
        body = "\n".join(lines[k + 1:k + 80])
        # 본문 아래 '목록·이전글·다음글'의 다른 글 제목이 섞이지 않게 자른다
        body = re.split(r"\n(?:목록|이전글|다음글|이벤트 자세히 보기)", body)[0]
        ev, why = build_event(
            src="mo", sid=no, title=title, url=url, org=org, body=title + "\n" + body,
            start=ds[0] if len(ds) >= 2 else None, end=ds[1] if len(ds) >= 2 else None)
        st["parsed"][no] = ev["id"] if ev else "skip:" + (why or "")
        if ev:
            events.append(ev)
        else:
            skipped[no] = why
    seen = [v for k, v in st["parsed"].items() if k in links and not v.startswith("skip:")]
    return {"events": events, "seen": seen, "listed": len(links), "skipped": skipped}


# ---- 한국관광공사 관광e배움터 진행 중인 이벤트 ----
TOUR = "https://touredu.visitkorea.or.kr/home/support/promotions/prgs"


def touredu(f, state, cfg):
    st = state.setdefault("touredu", {"parsed": {}})
    d = f.doc(TOUR)
    nos = list(dict.fromkeys(re.findall(r"/promotions/prgs/(\d+)", " ".join(d.xpath("//a/@href")))))
    events, skipped = [], {}
    for no in nos:
        if no in st["parsed"]:
            continue
        url = f"{TOUR}/{no}"
        try:
            v = f.doc(url)
        except Exception as e:
            skipped[no] = f"오류: {e}"[:120]
            continue
        lines = text_of(v.xpath("//body")[0]).splitlines()
        k = next((i for i, x in enumerate(lines) if re.search(r"\d{4}\.\d{2}\.\d{2}\s*~", x)), None)
        if k is None:
            st["parsed"][no] = "skip:기간 없음"
            continue
        title = lines[k - 1]
        s, e = period(lines[k])
        body = "\n".join(lines[k + 1:k + 40])
        ev, why = build_event(src="te", sid=no, title=title, url=url, org="한국관광공사 관광e배움터",
                              body=title + " 이벤트\n" + body, start=s, end=e)
        st["parsed"][no] = ev["id"] if ev else "skip:" + (why or "")
        if ev:
            events.append(ev)
        else:
            skipped[no] = why
    seen = [v for k, v in st["parsed"].items() if k in nos and not v.startswith("skip:")]
    return {"events": events, "seen": seen, "listed": len(nos), "skipped": skipped}
