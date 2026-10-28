# 도우미 봇 '뽀삐'가 찾아 둔 이벤트(data/bot_events.json)를 본 목록에 합친다.
# 스키마는 README의 '뽀삐가 찾은 이벤트'. 마감일·공연초대·지역 한정은 여기서 걸러 낸다.
import datetime as dt
import difflib
import re

from .extract import (
    classify, find_count, fix_url, is_region_limited, is_show_invite, make_id,
    norm_title, norm_url, pay_required, policy_block, tidy,
)
from .sources.aggregators import tidy_prize

BOT_PATH_NAME = "bot_events.json"

_TOKEN_KIND = {
    "퀴즈/퍼즐": "퀴즈",
    "댓글/단문": "댓글",
    "단순응모": "기타",
}


def clean_howto(text):
    """운영 메모(지역 한정이면 건너뜀 등)는 참여자에게 보여 주지 않는다."""
    t = text or ""
    t = re.sub(r"\([^)]*건너뜀[^)]*\)", "", t)
    t = re.sub(r"(?:^|[;])\s*[^;→]*건너뜀", "", t)
    t = re.sub(r"eventhouse\s*목록\s*→\s*공식\s*원문\s*확인\s*;?", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ;→")
    return t


def split_steps(text):
    text = clean_howto(text)
    if not text:
        return []
    if re.search(r"[①-⑩]", text):
        parts = [x.strip(" ;") for x in re.split(r"\s*[①-⑩]\s*", text) if x.strip(" ;")]
    elif "→" in text:
        parts = [x.strip(" ;") for x in text.split("→") if x.strip(" ;")]
    else:
        parts = [text]
    return [p[:160] for p in parts[:6]]


def infer_platform(url, platform=None):
    if platform and str(platform).strip():
        return str(platform).strip()
    u = (url or "").lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "forms.gle" in u or "docs.google.com/forms" in u:
        return "Google Form"
    if "form.naver.com" in u or "m.site.naver.com" in u or "naver.me" in u:
        return "Naver Form"
    if "blog.naver.com" in u or "cafe.naver.com" in u:
        return "Naver blog"
    if "smore.im" in u:
        return "smore"
    if "moaform.com" in u:
        return "web form"
    return "web"


def plat_hint(platform, url):
    p = (platform or "").lower()
    u = (url or "").lower()
    if "youtube" in p or "youtu.be" in u or "youtube.com" in u:
        return "yt"
    if "naver" in p or "blog.naver" in u or "form.naver" in u or "naver.me" in u or "m.site.naver" in u:
        return "naver"
    if "insta" in p or "instagram.com" in u:
        return "insta"
    return "web"


def _org_of(title):
    m = re.match(r"\[([^\]]+)\]", title or "")
    return m.group(1).strip() if m else None


def tidy_bot_prize(title, prize, org):
    if not prize:
        return None
    p = str(prize).strip()
    if "이벤트!!" in p:
        p = p.split("이벤트!!", 1)[1].strip()
    if org and p.startswith(org):
        p = p[len(org):].strip()
    p = re.sub(r"(?:단순응모|퀴즈/퍼즐|댓글/단문|설문/투표)", " ", p)
    p = re.sub(r"\s+", " ", p).strip(" -")
    return tidy_prize(p) or tidy(p)


def _kind_of(title, howto, prize, raw_prize):
    kind, _reasons, tags = classify(f"{title}\n{howto}\n{prize or ''}")
    token = None
    for key, val in _TOKEN_KIND.items():
        if key in (raw_prize or ""):
            token = val
            break
    if "설문/투표" in (raw_prize or ""):
        if re.search(r"설문|만족도|조사", title or ""):
            token = "설문"
        elif "투표" in (title or ""):
            token = "투표"
        else:
            token = "설문"
    if kind == "기타" and token:
        kind = token
    return kind, tags


def canonical_record(item):
    """queue 원본이나 이미 정리된 항목을 bot_events.json 스키마로 맞춘다. 실을 수 없으면 None."""
    if not isinstance(item, dict):
        return None
    title = tidy(item.get("title") or item.get("name") or "")
    url = fix_url(item.get("url") or item.get("entry_url") or "")
    deadline = str(item.get("deadline") or "")[:10]
    if not title or not url or not str(url).startswith("http"):
        return None
    try:
        dt.date.fromisoformat(deadline)
    except ValueError:
        return None
    org = _org_of(title)
    raw_prize = item.get("prize") or ""
    howto = clean_howto(item.get("how_to_enter") or item.get("steps") or "")
    prize = tidy_bot_prize(title, raw_prize, org)
    platform = infer_platform(url, item.get("platform"))
    source = item.get("source") or item.get("verified_source") or None
    blob = " ".join(x for x in (title, prize or "", howto, raw_prize) if x)
    if is_show_invite(blob) or is_region_limited(blob) or pay_required(blob):
        return None
    rec = {
        "title": title,
        "url": url,
        "deadline": deadline,
        "platform": platform,
        "prize": prize,
        "how_to_enter": howto or None,
    }
    if source:
        rec["source"] = str(source)[:180]
    return rec


def to_event(item, today):
    """스키마 항목 → 사이트 장부 형식. 마감이 지났거나 정책을 어기면 None."""
    rec = canonical_record(item)
    if not rec or rec["deadline"] < today:
        return None
    title = rec["title"]
    org = _org_of(title)
    show = re.sub(r"^\[[^\]]+\]\s*", "", title).strip() or title
    howto = rec.get("how_to_enter") or ""
    kind, tags = _kind_of(show, howto, rec.get("prize"), item.get("prize") or rec.get("prize") or "")
    steps = split_steps(howto)
    url = rec["url"]
    ev = {
        "id": make_id("pp", norm_url(url) or url),
        "title": show,
        "org": org,
        "kind": kind,
        "grade": "C",
        "tags": tags,
        "reasons": [],
        "prize": rec.get("prize"),
        "count": find_count(rec.get("prize")),
        "mode": "추첨" if re.search(r"추첨|명", rec.get("prize") or "") else None,
        "start": None,
        "end": rec["deadline"],
        "endTime": None,
        "announce": None,
        "min": None,
        "max": None,
        "who": None,
        "needs": ["팔로우·구독이 필요할 수 있어요"] if "팔로우 필요" in tags else [],
        "steps": steps,
        "place": None,
        "url": url,
        "checked": None,
        "cand": True,
        "src": "pp",
        "listUrl": None,
        "platHint": plat_hint(rec.get("platform"), url),
        "platform": rec.get("platform"),
        "bot": True,
        "status": "active",
        "srcUrls": [url],
    }
    if policy_block(ev):
        return None
    return ev


def _org_key(org):
    return re.sub(r"\(주\)|㈜|주식회사|\.\.+|…|\([^)]*\)|\s", "", org or "").lower()


def is_duplicate(existing, ev):
    """본 목록과 URL이 같거나, 마감일이 같고 제목·주최가 비슷하면 같은 이벤트."""
    nu = norm_url(ev.get("url"))
    nt = norm_title(ev.get("title") or "")
    og = _org_key(ev.get("org"))
    for e in existing:
        urls = [e.get("url"), e.get("listUrl"), *(e.get("srcUrls") or [])]
        if nu and any(norm_url(u) == nu for u in urls if u):
            return True
        if not ev.get("end") or ev.get("end") != e.get("end"):
            continue
        ot = norm_title(e.get("title") or "")
        if len(nt) < 6 or len(ot) < 6:
            continue
        oo = _org_key(e.get("org"))
        if og and oo and not (og in oo or oo in og or difflib.SequenceMatcher(None, og, oo).ratio() >= 0.6):
            continue
        if nt in ot or ot in nt or difflib.SequenceMatcher(None, nt, ot).ratio() >= 0.86:
            return True
    return False


def select_events(raw, existing, today):
    """마감 전·정책 통과·본 목록과 중복이 아닌 뽀삐 이벤트."""
    out, seen = [], set()
    for item in raw or []:
        ev = to_event(item, today)
        if not ev:
            continue
        key = norm_url(ev["url"]) or ev["url"]
        if key in seen or is_duplicate(existing, ev) or is_duplicate(out, ev):
            continue
        seen.add(key)
        out.append(ev)
    return out


def prune_records(raw, today):
    """파일에 남길 항목. (kept, dropped_count). 마감이 지난 것, 공연초대, 지역 한정만 뺀다."""
    kept, dropped = [], 0
    for item in raw or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        deadline = str(item.get("deadline") or "")[:10]
        try:
            dt.date.fromisoformat(deadline)
        except ValueError:
            dropped += 1
            continue
        if deadline < today:
            dropped += 1
            continue
        blob = " ".join(str(item.get(k) or "") for k in ("title", "name", "prize", "how_to_enter", "steps"))
        if is_show_invite(blob) or is_region_limited(blob):
            dropped += 1
            continue
        kept.append(item)
    return kept, dropped
