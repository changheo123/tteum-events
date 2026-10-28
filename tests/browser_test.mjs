// 실제 Chrome으로 사이트를 열어 화면·기능을 점검한다(Chrome DevTools 프로토콜, 외부 패키지 없음)
// 사용: node tests/browser_test.mjs <사이트 URL> <스크린샷 폴더>
import { spawn } from "node:child_process";
import { writeFileSync, existsSync } from "node:fs";

const URL_ = process.argv[2] || "http://127.0.0.1:8765/";
const OUT = process.argv[3] || ".";
const CHROME = [
  process.env.CHROME,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium",
].find(p => p && existsSync(p));
const PORT = 9333;
const proc = spawn(CHROME, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, "--no-first-run",
  "--no-sandbox", `--user-data-dir=${OUT}/chrome-prof`, "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));

let ws, seq = 0;
const pending = new Map();
function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}
async function ev(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + (r.exceptionDetails.exception?.description || ""));
  return r.result.value;
}
// 페이지가 다 그려질 때까지(카드가 생기고 문서 로드 완료) 최대 20초 기다린다
async function ready() {
  for (let i = 0; i < 80; i++) {
    await sleep(250);
    try { if (await ev(`document.readyState === 'complete' && document.querySelectorAll('.tk').length > 0`)) { await sleep(300); return; } } catch {}
  }
}
async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.data, "base64"));
}

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); };

try {
  let target;
  for (let i = 0; i < 120 && !target; i++) {  // Chrome 시작을 최대 30초 기다린다(러너가 느릴 때)
    await sleep(250);
    try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find(t => t.type === "page"); } catch {}
  }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener("open", r));
  const errors = [];
  ws.addEventListener("message", m => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { const p = pending.get(d.id); pending.delete(d.id); d.error ? p.rej(new Error(d.error.message)) : p.res(d.result); }
    if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.text);
    if (d.method === "Log.entryAdded" && d.params.entry.level === "error") errors.push(d.params.entry.text);
  });
  await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable");

  for (const [label, w, h, mobile] of [["mobile", 390, 844, true], ["pc", 1280, 900, false]]) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: mobile ? 2 : 1, mobile });
    await send("Page.navigate", { url: URL_ });
    await ready();
    const m = await ev(`({sw: document.documentElement.scrollWidth, iw: innerWidth, cards: document.querySelectorAll('.tk').length,
      chips: document.querySelectorAll('.chip').length, stamp: document.getElementById('stamp').textContent})`);
    check(`${label}: 가로 넘침 없음`, m.sw <= m.iw, `scrollWidth ${m.sw} / 화면 ${m.iw}`);
    check(`${label}: 카드 표시`, m.cards > 0, `${m.cards}장, 칩 ${m.chips}개, ${m.stamp}`);
    await shot(`${label}-top`);
  }

  // 아래 기능 점검은 휴대폰 화면 기준
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await send("Page.navigate", { url: URL_ }); await ready();
  await ev(`localStorage.clear()`);  // 지난 실행의 저장·참여함 기록을 지우고 시작
  await send("Page.reload"); await ready();
  const total = await ev(`DATA.events.filter(e => (!e.end || e.end >= kstToday()) && e.grade !== 'X').length`);
  const shown = await ev(`document.querySelectorAll('#list .tk').length`);
  check("데이터 건수 = 화면 카드 수(조건 많음 제외)", total === shown, `데이터 ${total} / 화면 ${shown}`);
  const chipSum = await ev(`[...document.querySelectorAll('.chip')].map(c => c.textContent)`);
  const wantChips = ["전체", "오늘 마감", "폼", "댓글", "퀴즈", "설문·투표", "체험단", "일반", "뽀삐 발굴"];
  check("카테고리 칩", wantChips.every(w => chipSum.some(t => t.startsWith(w))), chipSum.join(" | "));

  // 검색
  await ev(`(() => { const q = document.getElementById('q'); q.value = '스타벅스'; q.dispatchEvent(new Event('input')); })()`); await sleep(400);
  const sr = await ev(`[...document.querySelectorAll('#list .tk')].map(t => t.textContent.includes('스타벅스'))`);
  check("검색: '스타벅스' 결과가 모두 일치", sr.length > 0 && sr.every(Boolean), `${sr.length}건`);
  await ev(`(() => { const q = document.getElementById('q'); q.value = ''; q.dispatchEvent(new Event('input')); })()`); await sleep(400);

  // 정렬: 경품 가치순이면 첫 섹션 이후 금액이 내림차순
  await ev(`(() => { const s = document.getElementById('sort'); s.value = 'value'; s.dispatchEvent(new Event('change')); })()`); await sleep(300);
  const vals = await ev(`(() => { const ids = [...document.querySelectorAll('#list section:last-child .tk')].map(t => t.dataset.id);
    return ids.map(id => DATA.events.find(e => e.id === id).value).filter(v => v != null); })()`);
  check("정렬: 경품 가치순", vals.every((v, i) => i === 0 || vals[i - 1] >= v), vals.slice(0, 8).join(","));
  await ev(`(() => { const s = document.getElementById('sort'); s.value = 'due'; s.dispatchEvent(new Event('change')); })()`); await sleep(300);
  const dues = await ev(`[...document.querySelectorAll('#list .tk')].map(t => DATA.events.find(e => e.id === t.dataset.id).end).filter(Boolean)`);
  check("정렬: 마감 임박순", dues.every((v, i) => i === 0 || dues[i - 1] <= v), `${dues[0]} … ${dues.at(-1)}`);

  // 참여 방법 + 플랫폼 동시 필터
  await ev(`document.querySelector('.chip[data-k="댓글"]').click()`); await sleep(200);
  await ev(`(() => { const s = document.getElementById('fPlat'); s.value = 'yt'; s.dispatchEvent(new Event('change')); })()`); await sleep(300);
  const yt = await ev(`[...document.querySelectorAll('#list .tk')].map(t => { const e = DATA.events.find(x => x.id === t.dataset.id); return e.plats.includes('yt') && (e.entries || []).includes('comment'); })`);
  check("필터: 유튜브 + 댓글", yt.length > 0 && yt.every(Boolean), `${yt.length}건`);
  await ev(`document.getElementById('fReset').click()`); await ev(`document.querySelector('.chip[data-k="전체"]').click()`); await sleep(300);

  await ev(`(() => { const s = document.getElementById('fPrize'); s.value = 'gifticon'; s.dispatchEvent(new Event('change')); })()`); await sleep(300);
  const gifts = await ev(`[...document.querySelectorAll('#list .tk')].map(t => DATA.events.find(e => e.id === t.dataset.id).ptypes.includes('gifticon'))`);
  check("필터: 기프티콘", gifts.length > 0 && gifts.every(Boolean), `${gifts.length}건`);
  await ev(`document.getElementById('fReset').click()`); await sleep(200);

  // 무료 여부: 추가 비용 확인된 것 빼기
  await ev(`(() => { const c = document.getElementById('fNoCost'); c.checked = true; c.dispatchEvent(new Event('change')); })()`); await sleep(300);
  const tax = await ev(`[...document.querySelectorAll('#list .tk')].some(t => DATA.events.find(e => e.id === t.dataset.id).tax)`);
  check("필터: 제세공과금 있는 이벤트 제외", !tax);
  await ev(`document.getElementById('fReset').click()`); await sleep(300);

  // 상세 창 열기·원문 링크
  await ev(`document.querySelector('#list .tk [data-act="open"]').click()`); await sleep(400);
  const dlg = await ev(`({open: document.getElementById('dlg').open, link: document.querySelector('#dFoot a.go')?.href, title: document.getElementById('dTitle')?.textContent})`);
  check("상세 창 열림 + 응모 링크", dlg.open && /^https?:/.test(dlg.link || ""), `${dlg.title} → ${dlg.link}`);
  await shot("mobile-detail");
  await ev(`document.getElementById('dClose').click()`);

  // 저장·참여함(새로고침 후 유지)
  const fid = await ev(`(() => { const b = document.querySelector('#list .tk [data-act="fav"]'); const id = b.dataset.id; b.click(); return id; })()`); await sleep(300);
  await send("Page.reload"); await ready();
  const kept = await ev(`document.querySelector('#list .tk [data-act="fav"][data-id="${fid}"]')?.getAttribute('aria-pressed')`);
  check("저장 표시가 새로고침 후 유지", kept === "true");

  // 0건 카테고리 안내(0건인 칩이 있을 때만)
  const zeroChip = await ev(`[...document.querySelectorAll('.chip')].find(c => c.querySelector('.n').textContent === '0')?.dataset.k || ''`);
  if (zeroChip) {
    await ev(`document.querySelector('.chip[data-k="${zeroChip}"]').click()`); await sleep(300);
    const empty = await ev(`document.getElementById('list').textContent`);
    check("0건 카테고리 안내 문구", empty.includes("연동되지 않아"), zeroChip);
  }

  // 마감이 지난 이벤트는 데이터에도 화면에도 없고, 클라이언트 가드가 날짜를 자른다
  await ev(`document.querySelector('.chip[data-k="전체"]').click()`); await sleep(300);
  const guard = await ev(`({past: DATA.events.filter(e => e.end && e.end < kstToday()).length,
    shown: [...document.querySelectorAll('#list .tk')].filter(t => { const e = DATA.events.find(x => x.id === t.dataset.id); return e && e.end && e.end < kstToday(); }).length,
    fn: isCurrent({end:'2000-01-01'}) === false && isCurrent({end: kstToday()}) === true && isCurrent({}) === true,
    endedBox: !!document.getElementById('ended'),
    src: document.querySelectorAll('#src tr').length,
    bot: document.body.innerText.includes('뽀삐 발굴') && DATA.events.some(e => e.bot),
    cta: [...document.querySelectorAll('#list a.go')].some(a => a.textContent.includes('공식 페이지에서 참여'))})`);
  check("마감 지난 이벤트는 빼고 뽀삐·공식 링크를 표시", guard.past === 0 && guard.shown === 0 && guard.fn && !guard.endedBox && guard.src >= 8 && guard.bot && guard.cta,
    `과거 ${guard.past}/${guard.shown}, 출처 ${guard.src}, 뽀삐 ${guard.bot}, 버튼 ${guard.cta}`);
  const todayCards = await ev(`(() => { const nodes = [...document.querySelectorAll('#list .tk.today')]; return {n: nodes.length, ok: nodes.every(t => t.textContent.includes('오늘') && t.textContent.includes('마감'))}; })()`);
  check("오늘 마감 카드 강조", todayCards.n === 0 || todayCards.ok, `${todayCards.n}장`);

  // 원문 링크가 모두 http(s)
  const badLinks = await ev(`[...document.querySelectorAll('a.go')].filter(a => !/^https?:\\/\\//.test(a.href)).length`);
  check("모든 원문 링크가 http(s)", badLinks === 0);

  check("스크립트 오류 없음", errors.length === 0, errors.slice(0, 3).join(" / "));
} catch (e) {
  check("테스트 실행", false, String(e));
} finally {
  writeFileSync(`${OUT}/browser_results.json`, JSON.stringify(results, null, 1));
  for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}  ${r.detail}`);
  // GitHub Actions에서는 실패 항목을 주석(annotation)으로 남겨 로그인 없이도 원인을 볼 수 있게 한다
  if (process.env.GITHUB_ACTIONS) for (const r of results.filter(x => !x.ok)) console.log(`::error::브라우저 점검 실패: ${r.name} ${String(r.detail).replace(/\n/g, " ").slice(0, 300)}`);
  try { ws?.close(); } catch {}
  proc.kill();
  process.exit(results.every(r => r.ok) ? 0 : 1);
}
