#!/usr/bin/env python3
"""Local control panel. Bind 127.0.0.1 only. Default: leave it alone and it keeps running."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
_VENV_DIR = HERE / ".venv"
_VENV_PY = _VENV_DIR / "bin" / "python3"
if _VENV_PY.exists() and Path(sys.prefix).resolve() != _VENV_DIR.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])
HOST, PORT = "127.0.0.1", 8787


def _job_python() -> str:
    return str(_VENV_PY) if _VENV_PY.exists() else sys.executable
sys.path.insert(0, str(HERE))
from workflow_one import load_dotenv  # noqa: E402

load_dotenv(HERE / ".env")
_LOCK = threading.Lock()
ACTIVITY: dict = {
    "active": False,
    "kind": "",
    "lines": [],
    "done": True,
    "ok": True,
    "error": "",
}


def _activity_snapshot() -> dict:
    with _LOCK:
        return dict(ACTIVITY)


def _run_job(cmd: list[str], kind: str) -> None:
    env = os.environ.copy()
    env["ALLOW_LOCAL_LIVE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(HERE),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip()
            if not text:
                continue
            with _LOCK:
                ACTIVITY["lines"] = (ACTIVITY["lines"] + [text])[-80:]
        code = proc.wait(timeout=900)
        with _LOCK:
            ACTIVITY["ok"] = code == 0
            ACTIVITY["error"] = "" if code == 0 else "Run failed. See the log."
            ACTIVITY["lines"] = ACTIVITY["lines"] + (
                ["Done — in Late."] if code == 0 else ["Failed."]
            )
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            ACTIVITY["ok"] = False
            ACTIVITY["error"] = str(e)
            ACTIVITY["lines"] = ACTIVITY["lines"] + [str(e)]
    finally:
        with _LOCK:
            ACTIVITY["active"] = False
            ACTIVITY["done"] = True


def _start_job(cmd: list[str], kind: str) -> tuple[bool, str]:
    with _LOCK:
        if ACTIVITY.get("active"):
            return False, "Already creating a post. Wait for this one to finish."
        ACTIVITY.update(
            {
                "active": True,
                "kind": kind,
                "lines": ["Starting " + kind + "…"],
                "done": False,
                "ok": None,
                "error": "",
            }
        )
    threading.Thread(target=_run_job, args=(cmd, kind), daemon=True).start()
    return True, ""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>EagleEye — social OS</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600&family=Outfit:wght@300;400;500;600&display=swap" rel="stylesheet"/>
<style>
  :root {
    --bg:#07080A; --bg2:#0C0D11; --gold:#C9A227; --gold2:#E8C96A; --ink:#F4EFE4;
    --muted:#8E8674; --card:rgba(17,19,24,.86); --line:#2A271C; --ok:#8FCB8F; --warn:#E0B35A;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; min-height:100%; background:var(--bg); color:var(--ink);
    font-family:Outfit, ui-sans-serif, system-ui, sans-serif; }
  body {
    background:
      radial-gradient(1200px 500px at 10% -10%, rgba(201,162,39,.14), transparent 55%),
      radial-gradient(900px 420px at 110% 10%, rgba(201,162,39,.07), transparent 50%),
      linear-gradient(180deg, #07080A 0%, #0B0C10 100%);
  }
  .wrap { max-width:1180px; margin:0 auto; padding:28px 28px 64px; }
  header.top { display:flex; justify-content:space-between; align-items:flex-end; gap:24px;
    padding-bottom:22px; border-bottom:1px solid var(--line); margin-bottom:28px; }
  .brand { display:flex; gap:14px; align-items:center; }
  .mark { width:42px; height:42px; border-radius:50%;
    background:radial-gradient(circle at 40% 35%, #E8C96A, #C9A227 42%, #3a300c 70%, #07080A);
    box-shadow:0 0 0 1px #C9A227, 0 0 28px rgba(201,162,39,.35); }
  .brand h1 { margin:0; font-family:"Cormorant Garamond", serif; font-size:34px; font-weight:600;
    letter-spacing:.04em; color:var(--gold2); }
  .brand p { margin:2px 0 0; color:var(--muted); font-size:13px; letter-spacing:.16em; text-transform:uppercase; }
  .live { display:flex; align-items:center; gap:8px; font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--ok); box-shadow:0 0 10px var(--ok); }
  .dot.off { background:#5a3a3a; box-shadow:none; }
  .grid { display:grid; grid-template-columns: 1.15fr .85fr; gap:22px; }
  @media (max-width:960px){ .grid { grid-template-columns:1fr; } }
  .card { background:var(--card); border:1px solid var(--line); border-radius:18px; padding:22px 22px 20px;
    backdrop-filter: blur(10px); box-shadow: 0 20px 50px rgba(0,0,0,.35); }
  .card h2 { margin:0 0 14px; font-size:11px; letter-spacing:.2em; text-transform:uppercase; color:var(--gold); font-weight:500; }
  label { display:block; font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); margin:14px 0 7px; }
  input[type=text], input[type=time], input[type=number], input[type=date], input[type=url], textarea {
    width:100%; background:#08090C; color:var(--ink); border:1px solid var(--line);
    border-radius:10px; padding:11px 12px; font:inherit; color-scheme: dark; }
  input[type=date] { min-height:46px; font-size:16px; }
  textarea { min-height:120px; font-size:12px; line-height:1.45; }
  .row3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
  .days, .slots { display:flex; flex-wrap:wrap; gap:8px; }
  .days label { margin:0; text-transform:none; letter-spacing:0; font-size:13px; color:var(--ink);
    display:flex; align-items:center; gap:6px; padding:8px 10px; border:1px solid var(--line); border-radius:999px; }
  .days input { accent-color: var(--gold); }
  .slot { display:flex; gap:8px; align-items:center; }
  .slot input { width:128px; }
  .toggle { display:flex; align-items:center; gap:12px; font-size:16px; }
  .toggle input { width:18px; height:18px; accent-color:var(--gold); }
  button { background:linear-gradient(180deg, var(--gold2), var(--gold)); color:#07080A; border:0;
    border-radius:999px; padding:11px 18px; font-weight:600; cursor:pointer; letter-spacing:.04em; }
  button.ghost { background:transparent; color:var(--gold); border:1px solid var(--gold); }
  button.tiny { padding:6px 10px; font-size:12px; }
  .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }
  .ok { color:var(--ok); font-size:13px; min-height:1.3em; margin-top:12px; }
  .warn { color:var(--warn); font-size:13px; margin:8px 0 0; }
  .mixbar { display:flex; height:10px; border-radius:99px; overflow:hidden; border:1px solid var(--line); margin-top:8px; }
  .mixbar span { display:block; height:100%; }
  .n { background:#C9A227; } .c { background:#5B8C5A; } .e { background:#4A6280; }
  .legend { display:flex; gap:14px; font-size:12px; color:var(--muted); margin-top:8px; }
  .legend i { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
  .pipe { display:flex; flex-direction:column; gap:10px; }
  .step { display:grid; grid-template-columns:28px 1fr; gap:10px; align-items:start; }
  .num { width:28px; height:28px; border-radius:50%; border:1px solid var(--gold); color:var(--gold);
    display:flex; align-items:center; justify-content:center; font-size:12px; }
  .step b { display:block; font-size:14px; font-weight:500; }
  .step small { color:var(--muted); font-size:12px; }
  .preview { border-radius:14px; overflow:hidden; border:1px solid var(--line); background:#08090C; min-height:180px;
    display:flex; align-items:center; justify-content:center; color:var(--muted); }
  .preview img { width:100%; display:block; max-height:280px; object-fit:cover; }
  .meta { font-size:13px; color:var(--muted); line-height:1.5; margin-top:12px; }
  .meta strong { color:var(--ink); font-weight:500; }
  .pill { display:inline-block; border:1px solid var(--gold); color:var(--gold); border-radius:99px;
    padding:3px 9px; font-size:11px; letter-spacing:.08em; text-transform:uppercase; }
  .banner { display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;
    margin:-8px 0 22px; padding:14px 18px; border-radius:14px; border:1px solid var(--line);
    background:#0C0D11; }
  .banner .who { font-size:18px; font-weight:600; letter-spacing:.04em; }
  .banner .sub { color:var(--muted); font-size:13px; margin-top:2px; }
  .banner.armed { border-color:#2a4a2a; box-shadow:0 0 0 1px rgba(143,203,143,.18) inset; }
  .banner.armed .who { color:var(--ok); }
  .banner.paused { border-color:#4a2a2a; }
  .banner.paused .who { color:#E07A7A; }
  .banner.busy { border-color:var(--gold); background:linear-gradient(90deg, rgba(201,162,39,.16), #0C0D11 55%);
    animation: pulseBan 1.4s ease-in-out infinite; }
  .banner.busy .who { color:var(--gold2); }
  @keyframes pulseBan { 0%,100% { box-shadow:0 0 0 0 rgba(201,162,39,.35); }
    50% { box-shadow:0 0 28px 0 rgba(201,162,39,.45); } }
  .ov { position:fixed; inset:0; z-index:80; display:none; align-items:center; justify-content:center;
    background:rgba(4,5,7,.82); backdrop-filter:blur(10px); padding:24px; }
  .ov.on { display:flex; }
  .ovbox { width:min(640px, 100%); background:#0C0D11; border:1px solid var(--gold);
    border-radius:22px; padding:28px 26px 22px; box-shadow:0 30px 80px rgba(0,0,0,.55), 0 0 40px rgba(201,162,39,.18); }
  .ovbox h3 { margin:0; font-family:"Cormorant Garamond", serif; font-size:32px; color:var(--gold2); letter-spacing:.03em; }
  .ovbox .kicker { color:var(--gold); font-size:11px; letter-spacing:.22em; text-transform:uppercase; margin-bottom:6px; }
  .ringwrap { display:flex; justify-content:center; margin:18px 0 8px; }
  .ring { width:72px; height:72px; border-radius:50%; border:3px solid #2A271C; border-top-color:var(--gold);
    animation: spin 0.9s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .steps { display:flex; flex-direction:column; gap:8px; margin:18px 0 14px; }
  .st { display:grid; grid-template-columns:18px 1fr; gap:10px; align-items:center;
    font-size:14px; color:var(--muted); }
  .st .b { width:10px; height:10px; border-radius:50%; background:#2A271C; }
  .st.on { color:var(--gold2); }
  .st.on .b { background:var(--gold); box-shadow:0 0 10px var(--gold); animation: blink 1s infinite; }
  .st.done { color:var(--ok); }
  .st.done .b { background:var(--ok); box-shadow:none; animation:none; }
  @keyframes blink { 50% { opacity:.35; } }
  .log { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:11px; line-height:1.45;
    color:#C9C2B0; background:#08090C; border:1px solid var(--line); border-radius:10px;
    max-height:160px; overflow:auto; padding:10px 12px; white-space:pre-wrap; }
  button:disabled { opacity:.45; cursor:not-allowed; }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand">
      <div class="mark"></div>
      <div>
        <h1>EagleEye</h1>
        <p>Close anytime · reopen to edit · posting keeps running</p>
      </div>
    </div>
    <div class="live"><span class="dot" id="dot"></span><span id="live_lbl">automation on</span></div>
  </header>

  <div class="banner armed" id="banner">
    <div>
      <div class="who" id="ban_who">ARMED</div>
      <div class="sub" id="ban_sub">GitHub Actions posts even if this window is closed.</div>
    </div>
    <div class="sub" id="ban_next"></div>
  </div>

  <div class="ov" id="ov" aria-live="assertive">
    <div class="ovbox">
      <div class="kicker" id="ov_kick">Post creation</div>
      <h3 id="ov_title">Creating a post</h3>
      <div class="ringwrap"><div class="ring"></div></div>
      <div class="steps">
        <div class="st" id="st_research"><span class="b"></span><span>Finding a live golf clip</span></div>
        <div class="st" id="st_copy"><span class="b"></span><span>Writing the take</span></div>
        <div class="st" id="st_photo"><span class="b"></span><span>Grabbing the official thumbnail</span></div>
        <div class="st" id="st_pack"><span class="b"></span><span>Packaging X · IG · Reddit</span></div>
        <div class="st" id="st_late"><span class="b"></span><span>Sending to Late</span></div>
      </div>
      <div class="log" id="ov_log">Starting…</div>
    </div>
  </div>

  <div class="grid">
    <section class="card">
      <h2>Schedule</h2>
      <div class="toggle">
        <input id="enabled" type="checkbox"/>
        <span>Keep posting even if this Mac is off</span>
      </div>
      <p class="warn" id="status"></p>
      <label>Times · Eastern</label>
      <div id="slots" class="slots"></div>
      <button type="button" class="ghost tiny" id="add_slot" style="margin-top:8px">Add a time</button>
      <label>Mix</label>
      <div class="row3">
        <div><label>News</label><input id="mix_news" type="number" min="0" max="100"/></div>
        <div><label>Community</label><input id="mix_community" type="number" min="0" max="100"/></div>
        <div><label>Product</label><input id="mix_eagleeye" type="number" min="0" max="100"/></div>
      </div>
      <div class="mixbar" id="mixbar"><span class="n" id="b_n"></span><span class="c" id="b_c"></span><span class="e" id="b_e"></span></div>
      <div class="legend"><span><i class="n" style="background:#C9A227"></i>News</span>
        <span><i style="background:#5B8C5A"></i>Community</span>
        <span><i style="background:#4A6280"></i>Product</span></div>
      <p class="warn">Product is paused until app footage is ready. News + community are what build the following. Turn product up later.</p>
      <label>Days</label>
      <div class="days" id="days"></div>
      <label>Report email</label>
      <input id="report_email" type="text"/>
      <label>Campaign end date</label>
      <div class="row3" style="grid-template-columns:1fr 1fr">
        <input id="ends_on" type="date"/>
        <div id="ends_shown" style="display:flex;align-items:center;color:#E8C96A;font-size:20px;font-family:'Cormorant Garamond',serif;"></div>
      </div>
      <p class="warn" id="ends_lbl"></p>
      <p class="warn">Pick any date. It saves when you change it. Closing this window does not stop posting.</p>
      <details style="margin-top:16px">
        <summary style="cursor:pointer;color:var(--gold);letter-spacing:.12em;text-transform:uppercase;font-size:11px">YouTube channels</summary>
        <label>One per line · Name | UCxxxxxxxx</label>
        <textarea id="channels"></textarea>
      </details>
      <div class="actions">
        <button id="save">Save</button>
        <button class="ghost" id="run">Run next slot</button>
        <button class="ghost" id="run_all">Fill remaining today</button>
      </div>
      <p class="ok" id="msg"></p>
    </section>

    <div>
      <section class="card" style="margin-bottom:22px">
        <h2>Spotlight a link</h2>
        <p class="warn" style="margin-top:0">Paste a YouTube (or X / article) URL. This is extra — it does not replace the daily schedule.</p>
        <label>Link</label>
        <input id="spot_url" type="url" placeholder="https://www.youtube.com/watch?v=…"/>
        <div class="row3">
          <div><label>How many posts</label><input id="spot_count" type="number" min="1" max="8" value="3"/></div>
          <div><label>Hours between</label><input id="spot_every" type="number" min="2" max="48" value="4"/></div>
          <div style="display:flex;align-items:flex-end"><button class="ghost" id="spot_go">Schedule series</button></div>
        </div>
        <p class="ok" id="spot_msg"></p>
      </section>
      <section class="card" style="margin-bottom:22px">
        <h2>How a post is built</h2>
        <div class="pipe">
          <div class="step"><div class="num">1</div><div><b>Prefer video already on X</b><small>Official native videos. The tweet includes their status URL so X embeds the player.</small></div></div>
          <div class="step"><div class="num">2</div><div><b>YouTube if no X video</b><small>Then we unfurl the official YouTube URL. Never rip, never AI footage.</small></div></div>
          <div class="step"><div class="num">3</div><div><b>IG gets that same frame</b><small>The official video thumbnail. Skip IG if we don't have a real still.</small></div></div>
        </div>
      </section>
      <section class="card">
        <h2>Last run</h2>
        <div id="last_pill"></div>
        <div class="preview" id="prev">Nothing scheduled yet</div>
        <div class="meta" id="last_meta"></div>
      </section>
    </div>
  </div>
</div>
<script>
const DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const daysBox = document.getElementById("days");
DAYS.forEach((n,i) => {
  daysBox.insertAdjacentHTML("beforeend",
    `<label><input type="checkbox" id="d${i}" data-day="${i}"/> ${n}</label>`);
});
function show(t){ document.getElementById("msg").textContent = t; }
let busyTimer = null;
function setBusy(on, title, kicker){
  const ov = document.getElementById("ov");
  ov.className = "ov" + (on ? " on" : "");
  document.getElementById("run").disabled = on;
  document.getElementById("run_all").disabled = on;
  document.getElementById("spot_go").disabled = on;
  if (title) document.getElementById("ov_title").textContent = title;
  if (kicker) document.getElementById("ov_kick").textContent = kicker;
  if (on) {
    ["st_research","st_copy","st_photo","st_pack","st_late"].forEach(id => document.getElementById(id).className = "st");
    document.getElementById("ov_log").textContent = "Starting…";
    const ban = document.getElementById("banner");
    ban.className = "banner busy";
    document.getElementById("ban_who").textContent = "CREATING A POST";
    document.getElementById("ban_sub").textContent = "Do not close this window until this finishes.";
    document.getElementById("live_lbl").textContent = "creating now";
    document.getElementById("dot").className = "dot";
  }
}
function paintSteps(text){
  const t = (text||"").toLowerCase();
  const mark = (id, cond, done) => {
    const el = document.getElementById(id);
    if (done) el.className = "st done";
    else if (cond && el.className !== "st done") el.className = "st on";
  };
  mark("st_research", /lane|community|news pick|spotlight|finding/.test(t), /headline|embed/.test(t));
  mark("st_copy", /x copy|x chars|headline|grok/.test(t), /visual|official still|packaged/.test(t));
  mark("st_photo", /visual|official still|ytimg|og:image/.test(t), /packaged|reddit|twitter/.test(t));
  mark("st_pack", /packaged|reddit|twitter|instagram|source/.test(t), /\blate\b/.test(t));
  mark("st_late", /\blate\b/.test(t), /scheduled|published|submitted/.test(t));
}
async function pollBusy(){
  try {
    const r = await fetch("/api/activity");
    const a = await r.json();
    const log = (a.lines||[]).join("\n") || "Working…";
    document.getElementById("ov_log").textContent = log;
    const box = document.getElementById("ov_log");
    box.scrollTop = box.scrollHeight;
    paintSteps(log);
    if (a.active || a.ok === null) {
      setBusy(true, a.kind === "spotlight" ? "Building a series" : (a.kind === "fill" ? "Filling today's slots" : "Creating a post"),
        a.kind === "spotlight" ? "Spotlight" : "Live run");
      return;
    }
    if (busyTimer) { clearInterval(busyTimer); busyTimer = null; }
    setBusy(false);
    const msg = a.ok ? (a.kind === "spotlight"
      ? "Series is in Late. Independent of the daily times."
      : "In Late. Cloud posting still runs if you close this window.")
      : (a.error || "Run finished with an error.");
    show(msg);
    const sbox = document.getElementById("spot_msg");
    if (a.kind === "spotlight") sbox.textContent = msg;
    load();
  } catch (e) { /* keep polling */ }
}
function watchBusy(){
  if (busyTimer) clearInterval(busyTimer);
  pollBusy();
  busyTimer = setInterval(pollBusy, 450);
}
function paintMix(){
  const n = +document.getElementById("mix_news").value || 0;
  const c = +document.getElementById("mix_community").value || 0;
  const e = +document.getElementById("mix_eagleeye").value || 0;
  const t = n+c+e || 1;
  document.getElementById("b_n").style.width = (100*n/t)+"%";
  document.getElementById("b_c").style.width = (100*c/t)+"%";
  document.getElementById("b_e").style.width = (100*e/t)+"%";
}
["mix_news","mix_community","mix_eagleeye"].forEach(id => {
  document.getElementById(id).addEventListener("input", paintMix);
});
function renderSlots(times, nextMap){
  const box = document.getElementById("slots");
  box.innerHTML = "";
  (times && times.length ? times : ["08:30"]).forEach(t => {
    const nxt = (nextMap && nextMap[t]) ? nextMap[t] : "";
    const row = document.createElement("div");
    row.className = "slot";
    row.innerHTML = `<input type="time" value="${t}" data-slot/>
      <span style="color:#8E8674;font-size:12px;min-width:140px">${nxt ? "next "+nxt : ""}</span>
      <button type="button" class="ghost tiny" data-del>Remove</button>`;
    row.querySelector("[data-del]").onclick = () => row.remove();
    box.appendChild(row);
  });
}
document.getElementById("add_slot").onclick = () => {
  const times = [...document.querySelectorAll("[data-slot]")].map(el => el.value).filter(Boolean);
  times.push("18:00");
  renderSlots(times, {});
};
async function load(){
  const r = await fetch("/api/config");
  const d = await r.json();
  document.getElementById("enabled").checked = !!d.enabled;
  const creating = !!(d.activity && d.activity.active);
  document.getElementById("dot").className = "dot" + (d.enabled || creating ? "" : " off");
  document.getElementById("live_lbl").textContent = creating ? "creating now" : (d.enabled ? "automation on" : "paused");
  const ban = document.getElementById("banner");
  const nexts = (d.next_fires || []).map(x => x.next).filter(Boolean);
  document.getElementById("ban_next").textContent = nexts[0] ? ("Next slot  " + nexts[0] + " ET") : "";
  if (creating) {
    ban.className = "banner busy";
    document.getElementById("ban_who").textContent = "CREATING A POST";
    document.getElementById("ban_sub").textContent = "Research → take → official thumbnail → Late. Leave this open until it finishes.";
  } else if (d.enabled) {
    ban.className = "banner armed";
    document.getElementById("ban_who").textContent = "ARMED";
    document.getElementById("ban_sub").textContent = "GitHub Actions builds posts at 5:00 AM ET. Late publishes at each time below. Close this window anytime.";
  } else {
    ban.className = "banner paused";
    document.getElementById("ban_who").textContent = "PAUSED";
    document.getElementById("ban_sub").textContent = "Nothing will post until you turn it on and save.";
  }
  if (creating && !busyTimer) watchBusy();
  const times = (d.slots||[]).map(s => s.time).filter(Boolean);
  const nextMap = {};
  (d.next_fires || []).forEach(x => { if (x.time) nextMap[x.time] = x.next; });
  renderSlots(times.length ? times : [d.post_time || "08:30"], nextMap);
  document.getElementById("mix_news").value = (d.mix||{}).news ?? 40;
  document.getElementById("mix_community").value = (d.mix||{}).community ?? 40;
  document.getElementById("mix_eagleeye").value = (d.mix||{}).eagleeye ?? 20;
  paintMix();
  document.getElementById("report_email").value = d.report_email || "";
  document.getElementById("ends_on").value = d.ends_on || "";
  const shown = document.getElementById("ends_shown");
  if (d.ends_on) {
    const parts = d.ends_on.split("-");
    const pretty = parts.length===3 ? `${parts[1]}/${parts[2]}/${parts[0]}` : d.ends_on;
    shown.textContent = pretty;
    const end = new Date(d.ends_on + "T23:59:59");
    const days = Math.ceil((end - new Date()) / 86400000);
    document.getElementById("ends_lbl").textContent = days >= 0
      ? `Stops after ${d.ends_on} · ${days} day${days===1?"":"s"} left. Email when it ends.`
      : `Ended ${d.ends_on}. Pick a new date to start again.`;
  } else {
    shown.textContent = "not set";
    document.getElementById("ends_lbl").textContent = "Set an end date so this cannot run forever.";
  }
  (d.days || [0,1,2,3,4,5,6]).forEach(i => {
    const el = document.getElementById("d"+i); if (el) el.checked = true;
  });
  const ch = (d.community_channels||[]).map(c => `${c.name} | ${c.youtube_id}`).join("\n");
  document.getElementById("channels").value = ch;
  document.getElementById("status").textContent = d.enabled
    ? "GitHub fills every remaining slot. Late publishes. X embeds the official video URL. Instagram gets that clip's real thumbnail."
    : "Paused. Nothing posts until you turn it on and save.";
  const last = d.last;
  const prev = document.getElementById("prev");
  const meta = document.getElementById("last_meta");
  const pill = document.getElementById("last_pill");
  if (last && last.headline) {
    pill.innerHTML = last.packaged ? `<span class="pill">${last.packaged}</span>` : "";
    if (last.still) prev.innerHTML = `<img src="${last.still}" alt=""/>`;
    else prev.textContent = last.video_url || "Link post — no still";
    meta.innerHTML = `<strong>${last.headline}</strong><br>
      ${last.when || ""} · ${last.lane || ""} · Late ${last.status || ""} ${last.late_id ? last.late_id.slice(-8) : ""}<br>
      ${last.video_url ? "Embed: "+last.video_url : ""}
      ${last.photo_credit ? "<br>"+last.photo_credit : ""}`;
  }
}
function gather(){
  const days = [];
  DAYS.forEach((_,i) => { if (document.getElementById("d"+i).checked) days.push(i); });
  const channels = document.getElementById("channels").value.split("\n").map(line => {
    const p = line.split("|").map(s => s.trim()).filter(Boolean);
    if (p.length < 2) return null;
    return { name: p[0], youtube_id: p[1] };
  }).filter(Boolean);
  const slotTimes = [...document.querySelectorAll("[data-slot]")].map(el => el.value).filter(Boolean);
  return {
    enabled: document.getElementById("enabled").checked,
    post_time: slotTimes[0] || "08:30",
    slots: slotTimes.map(t => ({time: t})),
    mix: {
      news: +document.getElementById("mix_news").value,
      community: +document.getElementById("mix_community").value,
      eagleeye: +document.getElementById("mix_eagleeye").value
    },
    days,
    report_email: document.getElementById("report_email").value,
    ends_on: document.getElementById("ends_on").value,
    community_channels: channels
  };
}
document.getElementById("save").onclick = async () => {
  const r = await fetch("/api/config", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(gather()) });
  const d = await r.json();
  show(d.ok ? "Saved. You can close this window — reopen anytime to change times or the end date." : (d.error||"save failed"));
  load();
};
document.getElementById("ends_on").addEventListener("change", async () => {
  const r = await fetch("/api/config", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(gather()) });
  const d = await r.json();
  show(d.ok ? "End date saved." : (d.error||"save failed"));
  load();
});
async function kick(fill){
  setBusy(true, fill ? "Filling today's slots" : "Creating a post", fill ? "Fill remaining" : "Next slot");
  show("");
  const r = await fetch("/api/run", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({fill: !!fill}),
  });
  const d = await r.json();
  if (!d.started && d.error) {
    setBusy(false);
    show(d.error);
    return;
  }
  watchBusy();
}
document.getElementById("run").onclick = () => kick(false);
document.getElementById("run_all").onclick = () => kick(true);
document.getElementById("spot_go").onclick = async () => {
  const url = document.getElementById("spot_url").value.trim();
  const count = +document.getElementById("spot_count").value || 3;
  const every = +document.getElementById("spot_every").value || 4;
  const box = document.getElementById("spot_msg");
  if (!url) { box.textContent = "Paste a link first."; return; }
  box.textContent = "";
  setBusy(true, "Building a series", "Spotlight · "+count+" posts");
  const r = await fetch("/api/spotlight", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({url, count, every_hours: every}),
  });
  const d = await r.json();
  if (!d.started && d.error) {
    setBusy(false);
    box.textContent = d.error;
    return;
  }
  watchBusy();
};
load();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("dashboard: " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            return
        if path == "/api/config":
            sys.path.insert(0, str(HERE))
            from engine import slot_preview

            cfg = json.loads((HERE / "config.json").read_text())
            cfg["next_fires"] = slot_preview(cfg)
            state_path = HERE / "state" / "rotation.json"
            if state_path.exists():
                cfg["last"] = json.loads(state_path.read_text()).get("last")
            cfg["activity"] = _activity_snapshot()
            raw = json.dumps(cfg).encode()
            self._send(200, raw, "application/json")
            return
        if path == "/api/activity":
            self._send(200, json.dumps(_activity_snapshot()).encode(), "application/json")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if path == "/api/config":
            patch = json.loads(raw.decode() or "{}")
            cfg_path = HERE / "config.json"
            cfg = json.loads(cfg_path.read_text())
            old_channels = list(cfg.get("community_channels") or [])
            for k in ("enabled", "post_time", "slots", "mix", "days", "report_email", "ends_on", "community_channels"):
                if k in patch:
                    cfg[k] = patch[k]
            # Keep weight / mention handles when the UI only sends name|id lines.
            if "community_channels" in patch:
                old = {(c.get("youtube_id") or ""): c for c in old_channels}
                merged = []
                for c in cfg.get("community_channels") or []:
                    prev = old.get(c.get("youtube_id") or "") or {}
                    for field in ("weight", "x_handle", "ig_handle", "handle"):
                        if not c.get(field) and prev.get(field):
                            c[field] = prev[field]
                    merged.append(c)
                cfg["community_channels"] = merged
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
            self._send(200, b'{"ok":true}', "application/json")
            return
        if path == "/api/run":
            extra = json.loads(raw.decode() or "{}")
            cmd = [_job_python(), "-u", str(HERE / "run_daily.py"), "--live", "--kind", "auto"]
            kind = "fill" if extra.get("fill") else "next"
            if kind == "next":
                cmd.append("--one")
            started, err = _start_job(cmd, kind)
            self._send(
                200 if started else 409,
                json.dumps({"started": started, "error": err}).encode(),
                "application/json",
            )
            return
        if path == "/api/spotlight":
            extra = json.loads(raw.decode() or "{}")
            url = (extra.get("url") or "").strip()
            if not url:
                self._send(400, b'{"started":false,"error":"Paste a link first."}', "application/json")
                return
            count = str(int(extra.get("count") or 3))
            every = str(float(extra.get("every_hours") or 4))
            cmd = [
                _job_python(), "-u", str(HERE / "run_daily.py"), "--live",
                "--spotlight", url, "--count", count, "--every-hours", every,
            ]
            started, err = _start_job(cmd, "spotlight")
            self._send(
                200 if started else 409,
                json.dumps({"started": started, "error": err}).encode(),
                "application/json",
            )
            return
        self._send(404, b"not found", "text/plain")


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"EagleEye dashboard on {url} (localhost only)")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
