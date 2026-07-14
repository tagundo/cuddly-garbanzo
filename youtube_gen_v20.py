#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
youtube_gen_v20 — SIFAS/스쿠스타 YouTube 설명(제목) 생성기.

이 도구는 이제 브라우저 기반입니다 (sifas_fbx.py 와 동일한 방식).
PySide6(Qt) 없이 파이썬 표준 라이브러리만으로 로컬 웹 서버를 띄우고,
가능하면 독립 앱 창(pywebview)으로, 아니면 브라우저 창으로 UI를 엽니다.

Usage
    python3 youtube_gen_v20.py                 # 웹 UI 실행 (기본)
    python3 youtube_gen_v20.py --web           # 동일 (명시적으로)
    python3 youtube_gen_v20.py --no-browser    # 서버만 실행(창 안 열기; 원격/헤드리스)
    python3 youtube_gen_v20.py --port 8780      # 포트 지정 (기본: 자동)
    python3 youtube_gen_v20.py --data other.json   # 다른 데이터 파일 사용
    python3 youtube_gen_v20.py selftest        # 생성 로직 자체 점검
    python3 youtube_gen_v20.py generate --song "..." --artist "..." [옵션]  # 헤드리스 1회 생성

데이터(youtube_data.json)는 스크립트 옆에 저장되며, 저장 시 원자적 쓰기 +
번호 순환 백업(youtube_data_1..5.json)으로 보호됩니다.
"""

import os
import sys
import json
import shutil
import argparse
import threading
import traceback
from copy import deepcopy
from pathlib import Path
from datetime import datetime

# ---------------- Data file path ----------------
DATA_FILE = str(Path(__file__).with_name("youtube_data.json"))


# ==========================================================================
# Backup helpers: numbered rotation + atomic write
# ==========================================================================
def rotate_numbered_backups(json_path: str, max_backups: int = 5):
    """
    Same-directory numbered rotation:
      youtube_data_5.json (oldest) removed
      youtube_data_4.json -> _5.json
      ...
      youtube_data_1.json -> _2.json
      youtube_data.json   -> youtube_data_1.json (if exists)
    Returns the path of the newly created slot-1 backup, or None on first save.
    """
    p = Path(json_path).resolve()

    oldest = p.with_name(f"{p.stem}_{max_backups}.json")
    if oldest.exists():
        try:
            oldest.unlink()
        except Exception:
            pass

    for i in range(max_backups - 1, 0, -1):
        src = p.with_name(f"{p.stem}_{i}.json")
        dst = p.with_name(f"{p.stem}_{i+1}.json")
        if src.exists():
            try:
                src.replace(dst)
            except Exception:
                pass

    out = None
    if p.exists():
        out = p.with_name(f"{p.stem}_1.json")
        try:
            shutil.copy2(p, out)
        except Exception:
            out = None
    return str(out) if out else None


def atomic_write_json(json_path: str, data: dict):
    """Write to a temp file, flush+fsync, then atomic replace (no partial writes)."""
    p = Path(json_path).resolve()
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def append_import_log(base_path: str, level: str, message: str, detail: str = ""):
    """Append a line to import.log next to the working data file."""
    try:
        p = Path(base_path)
        log_path = p.with_name("import.log")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        if detail:
            line += f"\n{detail}"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ==========================================================================
# Default data + ensure / normalize / merge
# ==========================================================================
def get_default_data():
    return {
        "songs": {},
        "groups": {},
        "characters": {},
        "costumes": {},
        "mods": {},
        "song_categories": {"μ's": [], "Aqours": [], "Nijigasaki": [], "Solo": [], "Other": []},
        "costume_categories": {"μ's": [], "Aqours": [], "Nijigasaki": [], "Event": []},
        "character_costume_categories": {},
        "settings": {
            "aspect_ratios": ["16:9", "16:10", "4:3", "21:9"],
            "format_order": ["{playlist}", "{hashtags}", "{japanese}", "{korean}", "{english}"],
            "languages": ["japanese", "korean", "english"],
            "japanese_format": "{song} ({artist}, {mod}, {costume})[{ratio}][スクスタ {type}]",
            "korean_format": "{song} ({artist}, {mod}, {costume})[{ratio}][스쿠스타 {type}]",
            "english_format": "{song} ({artist}, {mod}, {costume})[{ratio}][SIFAS {type}]",
            "keep_mod_selection": False,
            "enable_costume_category_filter": False,
            "costume_category_whitelist": [],
        },
    }


def normalize_data(data):
    """Fill missing sections/settings and migrate legacy costume_categories.Character."""
    default = get_default_data()
    out = deepcopy(data) if isinstance(data, dict) else {}
    for k, v in default.items():
        if k not in out:
            out[k] = deepcopy(v)
    s = out.setdefault("settings", {})
    for k, v in default["settings"].items():
        s.setdefault(k, deepcopy(v) if isinstance(v, (list, dict)) else v)
    out.setdefault("character_costume_categories", {})

    # legacy migration: costume_categories["Character"] -> character_costume_categories
    cc = out.get("costume_categories", {})
    if isinstance(cc, dict) and "Character" in cc and isinstance(cc["Character"], dict):
        for ch, lst in cc["Character"].items():
            if not isinstance(lst, list):
                continue
            uniq, seen = [], set()
            for key in lst:
                if key in out.get("costumes", {}) and key not in seen:
                    uniq.append(key)
                    seen.add(key)
            base = out.setdefault("character_costume_categories", {}).get(ch, {})
            merged = list(base.get("Default", []))
            for k in uniq:
                if k not in merged:
                    merged.append(k)
            out.setdefault("character_costume_categories", {}).setdefault(ch, {})["Default"] = merged
        try:
            del out["costume_categories"]["Character"]
        except Exception:
            pass
    return out


def ensure_data(path=DATA_FILE):
    """Load (creating if missing), normalize, and persist the working data file."""
    p = Path(path).resolve()
    if not p.exists():
        atomic_write_json(path, get_default_data())
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        data = get_default_data()
    data = normalize_data(data)
    atomic_write_json(path, data)
    return data


def _merge_list_unique(base_list, add_list):
    if not isinstance(base_list, list):
        base_list = []
    seen = set(base_list)
    out = list(base_list)
    for x in add_list or []:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def merge_data_non_destructive(dst: dict, src: dict) -> dict:
    """Merge src into dst without overwriting existing values. Returns stats."""
    stats = {
        "songs_added": 0, "groups_added": 0, "characters_added": 0,
        "costumes_added": 0, "mods_added": 0,
        "song_cat_updates": 0, "costume_cat_updates": 0, "char_costume_cat_updates": 0,
        "settings_filled": 0,
    }

    for sec, key_stat in [
        ("songs", "songs_added"),
        ("groups", "groups_added"),
        ("characters", "characters_added"),
        ("costumes", "costumes_added"),
        ("mods", "mods_added"),
    ]:
        dst.setdefault(sec, {})
        for k, v in (src.get(sec) or {}).items():
            if k not in dst[sec]:
                dst[sec][k] = v
                stats[key_stat] += 1
            elif isinstance(dst[sec][k], dict) and isinstance(v, dict):
                for sk, sv in v.items():
                    if sk not in dst[sec][k]:
                        dst[sec][k][sk] = sv

    dst.setdefault("song_categories", {})
    for cat, arr in (src.get("song_categories") or {}).items():
        before = len(dst["song_categories"].get(cat, []))
        dst["song_categories"][cat] = _merge_list_unique(dst["song_categories"].get(cat, []), arr)
        stats["song_cat_updates"] += max(0, len(dst["song_categories"][cat]) - before)

    dst.setdefault("costume_categories", {})
    for cat, arr in (src.get("costume_categories") or {}).items():
        before = len(dst["costume_categories"].get(cat, []))
        dst["costume_categories"][cat] = _merge_list_unique(dst["costume_categories"].get(cat, []), arr)
        stats["costume_cat_updates"] += max(0, len(dst["costume_categories"][cat]) - before)

    dst.setdefault("character_costume_categories", {})
    for ch, cmap in (src.get("character_costume_categories") or {}).items():
        dst["character_costume_categories"].setdefault(ch, {})
        for cat, arr in (cmap or {}).items():
            before = len(dst["character_costume_categories"][ch].get(cat, []))
            dst["character_costume_categories"][ch][cat] = _merge_list_unique(
                dst["character_costume_categories"][ch].get(cat, []), arr
            )
            after = len(dst["character_costume_categories"][ch][cat])
            stats["char_costume_cat_updates"] += max(0, after - before)

    dst.setdefault("settings", {})
    for k, v in (src.get("settings") or {}).items():
        if k not in dst["settings"]:
            dst["settings"][k] = v
            stats["settings_filled"] += 1

    return stats


def looks_like_songs_map(d: dict) -> bool:
    """True if d looks like a bare {name: {japanese/korean/english}} songs map."""
    if not isinstance(d, dict):
        return False
    cnt, hit = 0, 0
    for v in list(d.values())[:10]:
        cnt += 1
        if isinstance(v, dict) and any(k in v for k in ("japanese", "korean", "english")):
            hit += 1
    return cnt > 0 and hit / cnt >= 0.6


# ==========================================================================
# Description generation (ported from the old Qt generate(); pure function)
# ==========================================================================
def _pick(d, lng, fallback):
    return d[lng] if isinstance(d, dict) and lng in d else fallback


def _clean_line(s):
    """Collapse empty {mod}/{costume} placeholders. Applied repeatedly until stable
    so that even the both-empty case (plain MV: no mod, no costume) reads cleanly,
    e.g. '(Artist, , )' -> '(Artist)'. The old Qt tool did a single pass and left a
    trailing ', '."""
    for _ in range(6):
        before = s
        s = s.replace("(, ", "(").replace(", )", ")").replace("()", "").replace(", ,", ",").strip()
        if s == before:
            break
    return s


def generate_description(data: dict, sel: dict) -> str:
    """
    Build the localized YouTube description text.

    sel keys: atype ("groups"|"characters"), artist, song, costume, ratio,
              vtype ("MOD"|"MV"), mods (list), solos (list of character keys).
    """
    settings = data.get("settings", {})
    languages = settings.get("languages", ["japanese", "korean", "english"])
    at = sel.get("atype", "groups")
    ak = sel.get("artist", "") or ""
    sk = sel.get("song", "") or ""
    sd = data.get("songs", {}).get(sk, {}) or {}
    ck = sel.get("costume", "") or ""
    cd = data.get("costumes", {}).get(ck, {}) or {}
    ar = sel.get("ratio", "") or ""
    tp = sel.get("vtype", "MOD") or "MOD"
    ms = list(sel.get("mods", []) or [])
    cpl = (cd.get("costume_playlist") or "").strip()

    if at == "characters":
        sels = list(sel.get("solos", []) or [])
        if not sels and ak:
            sels = [ak]
        chars = data.get("characters", {})
        ad_list = [chars.get(k, {}) for k in sels if k in chars]
        multiple_solo = len(ad_list) >= 2
        apls = [(ad.get("artist_playlist") or "").strip() for ad in ad_list]
        apl = "" if multiple_solo else (apls[0] if apls else "")

        if apl and cpl:
            playlist_line = f"{sels[0]} playlist : {apl} | Costume playlist : {cpl}"
        elif cpl:
            playlist_line = f"Costume playlist : {cpl}"
        elif apl:
            playlist_line = f"{sels[0]} playlist : {apl}"
        else:
            playlist_line = ""

        def artist_str(lng):
            return ", ".join(_pick(chars.get(k, {}), lng, k) for k in sels)

        extra_ht = " ".join(ad.get("hashtags", "") for ad in ad_list if ad.get("hashtags"))
    else:
        ad = data.get("groups", {}).get(ak, {}) or {}
        apl = (ad.get("artist_playlist") or "").strip()
        if apl and cpl:
            playlist_line = f"{ak} playlist : {apl} | Costume playlist : {cpl}"
        elif cpl:
            playlist_line = f"Costume playlist : {cpl}"
        elif apl:
            playlist_line = f"{ak} playlist : {apl}"
        else:
            playlist_line = ""

        def artist_str(lng):
            return _pick(ad, lng, ak)

        extra_ht = ad.get("hashtags", "") or ""

    mods = data.get("mods", {})

    def mod_str(lng):
        arr = []
        for m in ms:
            md = mods.get(m)
            if not md:
                continue
            nm = _pick(md, lng, m)
            if md.get("has_value"):
                v = md.get("default_value", "") or ""
                arr.append(f"{nm}({v})" if v else nm)
            else:
                arr.append(nm)
        return ", ".join(arr)

    def cos_str(lng):
        nm = cd.get(lng, "") or ""
        if not nm:
            return ""
        if lng == "japanese":
            return f"{nm}衣装"
        if lng == "korean":
            return f"{nm} 의상"
        return f"{nm} Costume"

    ht = "#スクスタ #SIFAS #스쿠스타 #lovelive #ラブライブ"
    if tp == "MOD":
        ht += " #MOD"
    if extra_ht:
        ht += " " + extra_ht

    vars_map = {"playlist": playlist_line, "hashtags": ht}
    for lng in languages:
        fmt = settings.get(f"{lng}_format", "")
        mp = {
            "song": _pick(sd, lng, sk),
            "artist": artist_str(lng),
            "mod": mod_str(lng),
            "costume": cos_str(lng),
            "ratio": f"[{ar}]" if ar else "",
            "type": tp,
        }
        try:
            line = _clean_line(fmt.format(**mp))
        except Exception:
            line = "Format Error"
        vars_map[lng] = line

    out_lines = []
    for item in settings.get("format_order", []):
        key = item.strip("{}")
        if vars_map.get(key):
            out_lines.append(vars_map[key])
    return "\n".join(out_lines)


# ==========================================================================
# Embedded web page (HTML + CSS + vanilla JS). Mirrors the old Qt UI.
# ==========================================================================
_WEB_PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>YouTube 설명 생성기</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%8E%AC%3C/text%3E%3C/svg%3E">
<style>
*{box-sizing:border-box}
:root{--bg:#1e1f22;--card:#2b2d31;--card2:#26282c;--in:#1a1b1e;--bd:#3a3d44;--fg:#e4e6ea;--mut:#9aa6b2;--acc:#5865f2;--acc2:#4752c4;--ok:#57b97f;--warn:#e0a63c;--del:#d05a5a}
body{font-family:-apple-system,Segoe UI,Roboto,'Noto Sans KR',sans-serif;margin:0;background:var(--bg);color:var(--fg);font-size:14px}
header{position:sticky;top:0;z-index:20;background:#1a1b1e;border-bottom:1px solid #000;padding:9px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
header h1{font-size:16px;margin:0;font-weight:700}
.toolbar{margin-left:auto;display:flex;align-items:center;gap:7px;flex-wrap:wrap}
#status{font-size:12px;color:var(--mut);min-width:80px;text-align:right}
#status.dirty{color:var(--warn)} #status.ok{color:var(--ok)} #status.err{color:var(--del)}
.cols{display:flex;gap:14px;align-items:flex-start;max-width:1180px;margin:14px auto;padding:0 16px}
.col{flex:1;min-width:0;display:flex;flex-direction:column;gap:14px}
@media(max-width:860px){.cols{flex-direction:column}}
.card{background:var(--card);border-radius:11px;padding:14px}
.card h2{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--mut);margin:0 0 11px;font-weight:700}
label{display:block;font-size:12px;color:var(--mut);margin:10px 0 3px}
label.first{margin-top:0}
.row{display:flex;gap:6px;align-items:center}
.row.wrap{flex-wrap:wrap}
select,input[type=text]{width:100%;background:var(--in);border:1px solid var(--bd);color:var(--fg);border-radius:7px;padding:8px;font-size:13px;font-family:inherit}
select:focus,input:focus{outline:none;border-color:var(--acc)}
button{background:#40444b;color:var(--fg);border:0;border-radius:7px;padding:8px 11px;cursor:pointer;font-size:13px;font-family:inherit;white-space:nowrap}
button:hover{filter:brightness(1.12)}
button.icon{padding:8px 10px;font-weight:700;line-height:1}
button.primary{background:var(--acc);color:#fff;font-weight:600}
button.ghost{background:#3a3d44}
button.danger:hover{background:var(--del);color:#fff}
button.sm{padding:5px 9px;font-size:12px}
.pill{background:var(--acc);color:#fff}
.hint{color:#7c8590;font-size:11.5px;margin:8px 2px 0;line-height:1.5}
.hint code{background:#00000055;padding:1px 5px;border-radius:4px;color:#bcd}
.list{background:var(--in);border:1px solid var(--bd);border-radius:7px;max-height:190px;overflow:auto;padding:4px}
.list .it{padding:6px 8px;border-radius:5px;cursor:pointer;font-size:13px;user-select:none;display:flex;gap:8px;align-items:center}
.list .it:hover{background:#ffffff10}
.list .it.sel{background:var(--acc);color:#fff}
.list .it input{margin:0}
.list.empty{color:var(--mut);font-size:12px;padding:10px;text-align:center}
.chk{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--fg);margin:8px 0;cursor:pointer}
.chk input{width:auto;margin:0}
#preview{white-space:pre-wrap;word-break:break-word;background:var(--in);border:1px solid var(--bd);border-radius:8px;padding:12px;min-height:130px;font-size:13.5px;line-height:1.6;-webkit-user-select:text;user-select:text}
.hidden{display:none!important}
.grow{flex:1;min-width:0}
.tag{font-size:11px;color:var(--mut)}
.modal-bg{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;z-index:100;padding:16px}
.modal{background:var(--card);border-radius:12px;padding:18px;width:100%;max-width:460px;max-height:90vh;overflow:auto}
.modal h3{margin:0 0 12px;font-size:15px}
.modal .btns{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#000d;color:#fff;padding:9px 16px;border-radius:8px;font-size:13px;z-index:200;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}
textarea{width:100%;background:var(--in);border:1px solid var(--bd);color:var(--fg);border-radius:7px;padding:9px;font-size:13px;font-family:ui-monospace,Menlo,monospace;min-height:220px;resize:vertical}
</style></head><body>
<header>
  <h1>🎬 YouTube 설명 생성기</h1>
  <div class="toolbar">
    <span id="status"></span>
    <button class="sm" onclick="doBackup()">백업</button>
    <button class="sm" onclick="openImport()">Import JSON</button>
    <button class="sm" onclick="location.href='/api/export'">Export ⭳</button>
    <button class="sm primary" onclick="saveNow()">저장</button>
  </div>
</header>

<div class="cols">
 <!-- ================= LEFT ================= -->
 <div class="col">
  <div class="card">
   <h2>선택 / 관리</h2>

   <label class="first">Artist Type</label>
   <select id="atype" onchange="onAtype()"><option>groups</option><option>characters</option></select>

   <label>Artist</label>
   <div class="row">
    <select id="artist" class="grow" onchange="onArtist()"></select>
    <button class="icon" title="추가" onclick="crudArtist('add')">＋</button>
    <button class="icon" title="편집" onclick="crudArtist('edit')">✎</button>
    <button class="icon danger" title="삭제" onclick="crudArtist('del')">✕</button>
   </div>
   <div class="row" id="soloAddRow" style="margin-top:6px">
    <button class="sm grow" onclick="soloAdd()">＋ 현재 Artist를 Solo에 추가</button>
   </div>

   <label>Song</label>
   <div class="row" style="margin-bottom:6px">
    <span class="tag">Category</span>
    <select id="songCat" class="grow" onchange="onSongCat()"></select>
   </div>
   <div class="row">
    <select id="song" class="grow" onchange="onSong()"></select>
    <button class="icon" title="추가" onclick="crudSong('add')">＋</button>
    <button class="icon" title="편집" onclick="crudSong('edit')">✎</button>
    <button class="icon danger" title="삭제" onclick="crudSong('del')">✕</button>
   </div>

   <div id="soloBox">
    <label>Selected Solos</label>
    <div class="list" id="soloList"></div>
    <div class="row wrap" style="margin-top:6px">
     <button class="sm" onclick="soloDel()">선택 제거</button>
     <button class="sm" onclick="soloClear()">모두 지우기</button>
    </div>
   </div>

   <label>Costume</label>
   <div class="row" style="margin-bottom:6px">
    <span class="tag">Category</span>
    <select id="costumeCat" class="grow" onchange="onCostumeCat()"></select>
   </div>
   <div class="row">
    <select id="costume" class="grow" onchange="onCostume()"></select>
    <button class="icon" title="추가" onclick="crudCostume('add')">＋</button>
    <button class="icon" title="편집" onclick="crudCostume('edit')">✎</button>
    <button class="icon danger" title="삭제" onclick="crudCostume('del')">✕</button>
   </div>
   <div class="row" style="margin-top:6px">
    <button class="sm ghost grow" onclick="noCostume()">No Costume (의상 없음)</button>
   </div>
  </div>

  <div class="card">
   <h2>Costume 필터</h2>
   <label class="chk"><input type="checkbox" id="cfEnable" onchange="onFilterChange()"> 카테고리 화이트리스트 사용</label>
   <div class="list" id="cfList"></div>
   <div class="hint">체크한 카테고리에 속한 의상만 Costume 목록에 표시됩니다.</div>
  </div>

  <div class="card" id="charcosCard">
   <h2>CharacterCostume (캐릭터별)</h2>
   <div class="tag" id="charcosWho" style="margin-bottom:6px"></div>
   <label class="first">Category</label>
   <div class="row">
    <select id="ccCat" class="grow" onchange="renderCharcos()"></select>
    <button class="icon" title="카테고리 추가" onclick="ccCatAdd()">＋</button>
    <button class="icon" title="이름 변경" onclick="ccCatRename()">✎</button>
    <button class="icon danger" title="카테고리 삭제" onclick="ccCatDel()">✕</button>
   </div>
   <label>이 카테고리의 의상 (클릭 → Costume 선택)</label>
   <div class="list" id="ccList"></div>
   <label>카테고리에 의상 추가</label>
   <div class="row">
    <select id="ccAdd" class="grow"></select>
    <button class="sm" onclick="ccAddToCat()">추가</button>
    <button class="sm danger" onclick="ccRemoveFromCat()">선택 제거</button>
   </div>
  </div>

  <div class="card">
   <h2>Mods</h2>
   <div class="row wrap" style="margin-bottom:8px">
    <button class="sm" onclick="crudMod('add')">＋ 추가</button>
    <button class="sm" onclick="crudMod('edit')">✎ 편집</button>
    <button class="sm danger" onclick="crudMod('del')">✕ 삭제</button>
   </div>
   <div class="list" id="modList"></div>
  </div>

  <div class="card">
   <h2>옵션</h2>
   <label class="first">Aspect Ratio</label>
   <div class="row">
    <select id="ratio" class="grow" onchange="onRatio()"></select>
    <button class="sm" onclick="editRatios()">편집</button>
   </div>
   <label>Video Type</label>
   <select id="vtype" onchange="onVtype()"><option>MOD</option><option>MV</option></select>
  </div>
 </div>

 <!-- ================= RIGHT ================= -->
 <div class="col">
  <div class="card">
   <h2>미리보기</h2>
   <div id="preview"></div>
   <div class="row" style="margin-top:10px">
    <button class="primary grow" onclick="copyOut()">📋 클립보드로 복사</button>
   </div>
  </div>

  <div class="card">
   <h2>줄 순서 (Line Order)</h2>
   <div class="list" id="orderList"></div>
   <div class="row wrap" style="margin-top:8px">
    <button class="sm" onclick="orderMove(-1)">⬆️ 위로</button>
    <button class="sm" onclick="orderMove(1)">⬇️ 아래로</button>
   </div>
   <div class="hint">사용 가능한 줄: <code>{playlist}</code> <code>{japanese}</code> <code>{korean}</code> <code>{english}</code> <code>{hashtags}</code></div>
  </div>

  <div class="card">
   <h2>포맷 (언어별 제목 템플릿)</h2>
   <div id="fmtBox"></div>
   <div class="hint">사용 가능한 변수: <code>{song}</code> <code>{artist}</code> <code>{mod}</code> <code>{costume}</code> <code>{ratio}</code> <code>{type}</code></div>
  </div>
 </div>
</div>

<div id="modalRoot"></div>
<div id="toast" class="toast"></div>

<script>
"use strict";
// ---------------- state ----------------
let DATA = null;
const S = { atype:"groups", artist:"", songCat:"All", song:"", costumeCat:"All",
            costume:"", ratio:"", vtype:"MOD", mods:[], solos:[], ccCat:"" };
let saveTimer = null;

function el(id){ return document.getElementById(id); }
function setStatus(t, cls){ const s=el('status'); s.textContent=t; s.className=cls||''; }
function toast(t){ const e=el('toast'); e.textContent=t; e.classList.add('show'); setTimeout(()=>e.classList.remove('show'),1400); }

// ---------------- API ----------------
async function apiGet(u){ const r=await fetch(u); return r.json(); }
async function apiPost(u,b){ const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}); return r.json(); }

function markDirty(){
  setStatus('● 저장 안 됨','dirty');
  clearTimeout(saveTimer);
  saveTimer=setTimeout(saveNow, 600);
}
async function saveNow(){
  clearTimeout(saveTimer);
  setStatus('저장 중…');
  try{
    const j=await apiPost('/api/save',{data:DATA});
    if(j.ok) setStatus('저장됨 ✓ '+(j.time||''),'ok');
    else setStatus('저장 실패','err');
  }catch(e){ setStatus('저장 실패: '+e,'err'); }
}
async function doBackup(){
  const j=await apiPost('/api/backup',{});
  toast(j.ok?('백업 생성: '+(j.name||'')):'백업 실패');
}

// ---------------- generation (mirror of Python generate_description) --------
function pick(d,lng,fb){ return (d && Object.prototype.hasOwnProperty.call(d,lng)) ? d[lng] : fb; }
function replaceAllStr(s,a,b){ return s.split(a).join(b); }
function pyFormat(fmt,mp){
  let out='', i=0; const n=fmt.length;
  while(i<n){
    const c=fmt[i];
    if(c==='{'){
      if(fmt[i+1]==='{'){ out+='{'; i+=2; continue; }
      const j=fmt.indexOf('}', i+1);
      if(j<0) throw new Error("single '{'");
      let name=fmt.slice(i+1,j).split(':')[0].split('!')[0];
      if(!Object.prototype.hasOwnProperty.call(mp,name)) throw new Error('KeyError '+name);
      const v=mp[name]; out+=(v==null?'':String(v)); i=j+1;
    } else if(c==='}'){
      if(fmt[i+1]==='}'){ out+='}'; i+=2; continue; }
      throw new Error("single '}'");
    } else { out+=c; i++; }
  }
  return out;
}
function generate(){
  if(!DATA){ return; }
  const st=DATA.settings||{};
  const languages=st.languages||['japanese','korean','english'];
  const at=S.atype, ak=S.artist||'', sk=S.song||'';
  const sd=(DATA.songs||{})[sk]||{};
  const ck=S.costume||''; const cd=(DATA.costumes||{})[ck]||{};
  const ar=S.ratio||''; const tp=S.vtype||'MOD';
  const ms=S.mods.slice();
  const cpl=((cd.costume_playlist||'')+'').trim();
  let playlist_line='', artistStr, extra_ht='';

  if(at==='characters'){
    let sels=S.solos.slice(); if(!sels.length && ak) sels=[ak];
    const chars=DATA.characters||{};
    const ad_list=sels.filter(k=>k in chars).map(k=>chars[k]);
    const multiple=ad_list.length>=2;
    const apls=ad_list.map(ad=>((ad.artist_playlist||'')+'').trim());
    const apl=multiple?'':(apls.length?apls[0]:'');
    if(apl&&cpl) playlist_line=sels[0]+' playlist : '+apl+' | Costume playlist : '+cpl;
    else if(cpl) playlist_line='Costume playlist : '+cpl;
    else if(apl) playlist_line=sels[0]+' playlist : '+apl;
    artistStr=lng=>sels.map(k=>pick(chars[k]||{},lng,k)).join(', ');
    extra_ht=ad_list.filter(ad=>ad.hashtags).map(ad=>ad.hashtags).join(' ');
  } else {
    const ad=(DATA.groups||{})[ak]||{};
    const apl=((ad.artist_playlist||'')+'').trim();
    if(apl&&cpl) playlist_line=ak+' playlist : '+apl+' | Costume playlist : '+cpl;
    else if(cpl) playlist_line='Costume playlist : '+cpl;
    else if(apl) playlist_line=ak+' playlist : '+apl;
    artistStr=lng=>pick(ad,lng,ak);
    extra_ht=ad.hashtags||'';
  }

  const mods=DATA.mods||{};
  const modStr=lng=>{
    const arr=[];
    for(const m of ms){ const md=mods[m]; if(!md) continue;
      const nm=pick(md,lng,m);
      if(md.has_value){ const v=md.default_value||''; arr.push(v?(nm+'('+v+')'):nm); }
      else arr.push(nm);
    }
    return arr.join(', ');
  };
  const cosStr=lng=>{ const nm=(cd[lng]||''); if(!nm) return '';
    if(lng==='japanese') return nm+'衣装'; if(lng==='korean') return nm+' 의상'; return nm+' Costume'; };

  let ht='#スクスタ #SIFAS #스쿠스타 #lovelive #ラブライブ';
  if(tp==='MOD') ht+=' #MOD'; if(extra_ht) ht+=' '+extra_ht;

  const vmap={playlist:playlist_line, hashtags:ht};
  for(const lng of languages){
    const fmt=st[lng+'_format']||'';
    const mp={song:pick(sd,lng,sk), artist:artistStr(lng), mod:modStr(lng),
              costume:cosStr(lng), ratio: ar?('['+ar+']'):'', type:tp};
    let line;
    try{
      line=pyFormat(fmt,mp);
      for(let p=0;p<6;p++){ const b=line;
        line=replaceAllStr(line,'(, ','('); line=replaceAllStr(line,', )',')');
        line=replaceAllStr(line,'()',''); line=replaceAllStr(line,', ,',','); line=line.trim();
        if(line===b) break; }
    }catch(e){ line='Format Error'; }
    vmap[lng]=line;
  }
  const order=st.format_order||[];
  const lines=[];
  for(const item of order){ const key=item.replace(/^[{}]+|[{}]+$/g,''); if(vmap[key]) lines.push(vmap[key]); }
  el('preview').textContent=lines.join('\n');
}

// ---------------- select helpers ----------------
function fillSelect(sel, items, current){
  sel.innerHTML='';
  for(const it of items){ const o=document.createElement('option'); o.value=it; o.textContent=it; sel.appendChild(o); }
  if(current && items.includes(current)) sel.value=current;
  else if(items.length) sel.value=items[0];
  else sel.value='';
  return sel.value;
}

// ---------------- costume filtering (mirror of Qt) ----------------
function whitelistAllowed(k){
  const s=DATA.settings||{};
  if(!s.enable_costume_category_filter) return true;
  const wl=(s.costume_category_whitelist||[]).map(x=>(''+x).trim()).filter(Boolean);
  if(!wl.length) return true;
  const cc=DATA.costume_categories||{};
  for(const cat of wl){ const arr=cc[cat]; if(Array.isArray(arr)&&arr.includes(k)) return true; }
  return false;
}
function costumeItems(){
  let keys=Object.keys(DATA.costumes||{});
  const cat=S.costumeCat;
  if(cat && cat!=='All'){ const pool=(DATA.costume_categories||{})[cat]||[]; keys=pool.filter(k=>k in (DATA.costumes||{})); }
  return keys.filter(whitelistAllowed);
}
function songItems(){
  let keys=Object.keys(DATA.songs||{});
  const cat=S.songCat;
  if(cat && cat!=='All'){ const pool=(DATA.song_categories||{})[cat]||[]; keys=pool.filter(k=>k in (DATA.songs||{})); }
  return keys;
}

// ---------------- renderers ----------------
function renderArtist(){
  const items=Object.keys(DATA[S.atype]||{});
  S.artist=fillSelect(el('artist'), items, S.artist);
  const isChar=S.atype==='characters';
  el('soloBox').classList.toggle('hidden', !isChar);
  el('soloAddRow').classList.toggle('hidden', !isChar);
  el('charcosCard').classList.toggle('hidden', !isChar);
}
function renderSongCat(){
  const cats=['All',...Object.keys(DATA.song_categories||{})];
  S.songCat=fillSelect(el('songCat'), cats, S.songCat);
}
function renderSong(){ S.song=fillSelect(el('song'), songItems(), S.song); }
function renderCostumeCat(){
  const cats=['All',...Object.keys(DATA.costume_categories||{})];
  S.costumeCat=fillSelect(el('costumeCat'), cats, S.costumeCat);
}
function renderCostume(){ S.costume=fillSelect(el('costume'), costumeItems(), S.costume); }
function renderRatios(){ S.ratio=fillSelect(el('ratio'), DATA.settings.aspect_ratios||[], S.ratio); }

function renderSolos(){
  const box=el('soloList'); box.innerHTML='';
  if(!S.solos.length){ box.className='list empty'; box.textContent='(비어 있음) — 캐릭터 여러 명을 Solo로 추가'; return; }
  box.className='list';
  S.solos.forEach((k,idx)=>{
    const d=document.createElement('div'); d.className='it'; d.textContent=k;
    d.onclick=()=>{ d.classList.toggle('sel'); };
    box.appendChild(d);
  });
}
function renderMods(){
  const box=el('modList'); const keys=Object.keys(DATA.mods||{});
  box.innerHTML='';
  if(!keys.length){ box.className='list empty'; box.textContent='(mods 없음)'; return; }
  box.className='list';
  S.mods=S.mods.filter(m=>keys.includes(m));
  keys.forEach(k=>{
    const d=document.createElement('div'); d.className='it';
    const cb=document.createElement('input'); cb.type='checkbox'; cb.checked=S.mods.includes(k);
    cb.onclick=(e)=>{ e.stopPropagation(); toggleMod(k,cb.checked); };
    const sp=document.createElement('span'); sp.textContent=k;
    const md=DATA.mods[k]; if(md&&md.has_value){ const t=document.createElement('span'); t.className='tag'; t.textContent='(value)'; sp.appendChild(document.createTextNode(' ')); sp.appendChild(t); }
    d.appendChild(cb); d.appendChild(sp);
    d.onclick=()=>{ cb.checked=!cb.checked; toggleMod(k,cb.checked); };
    box.appendChild(d);
  });
}
function toggleMod(k,on){
  const i=S.mods.indexOf(k);
  if(on && i<0) S.mods.push(k);
  if(!on && i>=0) S.mods.splice(i,1);
  generate();
}
function renderFilter(){
  el('cfEnable').checked=!!DATA.settings.enable_costume_category_filter;
  const wl=new Set(DATA.settings.costume_category_whitelist||[]);
  const box=el('cfList'); box.innerHTML=''; box.className='list';
  const cats=Object.keys(DATA.costume_categories||{});
  if(!cats.length){ box.className='list empty'; box.textContent='(카테고리 없음)'; return; }
  cats.forEach(c=>{
    const d=document.createElement('div'); d.className='it';
    const cb=document.createElement('input'); cb.type='checkbox'; cb.checked=wl.has(c); cb.dataset.cat=c;
    cb.onclick=(e)=>e.stopPropagation();
    cb.onchange=onFilterChange;
    const sp=document.createElement('span'); sp.textContent=c;
    d.appendChild(cb); d.appendChild(sp);
    d.onclick=()=>{ cb.checked=!cb.checked; onFilterChange(); };
    box.appendChild(d);
  });
}
function onFilterChange(){
  DATA.settings.enable_costume_category_filter=el('cfEnable').checked;
  const wl=[];
  el('cfList').querySelectorAll('input[type=checkbox]').forEach(cb=>{ if(cb.checked) wl.push(cb.dataset.cat); });
  DATA.settings.costume_category_whitelist=wl;
  renderCostume(); renderCharcos(); generate(); markDirty();
}
function renderOrder(){
  const box=el('orderList'); box.innerHTML=''; box.className='list';
  (DATA.settings.format_order||[]).forEach((it,idx)=>{
    const d=document.createElement('div'); d.className='it'+(idx===orderSel?' sel':''); d.textContent=it;
    d.onclick=()=>{ orderSel=idx; renderOrder(); };
    box.appendChild(d);
  });
}
let orderSel=-1;
function orderMove(dir){
  const arr=DATA.settings.format_order||[];
  const i=orderSel; if(i<0) return;
  const j=i+dir; if(j<0||j>=arr.length) return;
  [arr[i],arr[j]]=[arr[j],arr[i]]; orderSel=j;
  renderOrder(); generate(); markDirty();
}
function renderFormats(){
  const box=el('fmtBox'); box.innerHTML='';
  (DATA.settings.languages||[]).forEach(lng=>{
    const lab=document.createElement('label'); lab.textContent=lng; box.appendChild(lab);
    const inp=document.createElement('input'); inp.type='text'; inp.value=DATA.settings[lng+'_format']||'';
    inp.oninput=()=>{ DATA.settings[lng+'_format']=inp.value; generate(); markDirty(); };
    box.appendChild(inp);
  });
}

// ---------------- CharacterCostume ----------------
function ensureCharcos(ak){
  DATA.character_costume_categories=DATA.character_costume_categories||{};
  const cc=DATA.character_costume_categories[ak]||(DATA.character_costume_categories[ak]={});
  if(!Object.keys(cc).length) cc.Default=[];
  return cc;
}
function renderCharcos(){
  if(S.atype!=='characters' || !S.artist){ el('ccCat').innerHTML=''; el('ccList').innerHTML=''; el('ccAdd').innerHTML=''; el('charcosWho').textContent=''; return; }
  el('charcosWho').textContent='캐릭터: '+S.artist;
  const cc=ensureCharcos(S.artist);
  const cats=Object.keys(cc);
  S.ccCat=fillSelect(el('ccCat'), cats, S.ccCat);
  const cat=S.ccCat||'Default';
  const lst=cc[cat]||[];
  // list
  const box=el('ccList'); box.innerHTML='';
  if(!lst.length){ box.className='list empty'; box.textContent='(비어 있음)'; }
  else{
    box.className='list';
    lst.forEach(k=>{
      const d=document.createElement('div'); d.className='it'+(ccSel===k?' sel':''); d.textContent=k;
      d.onclick=()=>{ ccSel=k; setCostumeFromCharcos(k); renderCharcos(); };
      box.appendChild(d);
    });
  }
  // candidates
  const cand=Object.keys(DATA.costumes||{}).filter(k=>!lst.includes(k) && whitelistAllowed(k));
  fillSelect(el('ccAdd'), cand, el('ccAdd').value);
}
let ccSel="";
function setCostumeFromCharcos(k){
  // Wire the (previously dead) CharacterCostume selection to the global Costume.
  if(!(k in (DATA.costumes||{}))) return;
  S.costume=k; S.costumeCat='All';
  renderCostumeCat(); renderCostume(); generate();
}
function ccCatAdd(){
  openForm('새 카테고리',[{key:'name',label:'카테고리 이름',type:'text'}],{},(v)=>{
    const name=(v.name||'').trim(); if(!name) return;
    const cc=ensureCharcos(S.artist); if(name in cc){ toast('이미 있음'); return; }
    cc[name]=[]; S.ccCat=name; renderCharcos(); markDirty();
  });
}
function ccCatRename(){
  const old=S.ccCat; if(!old) return;
  openForm('카테고리 이름 변경',[{key:'name',label:'새 이름',type:'text'}],{name:old},(v)=>{
    const name=(v.name||'').trim(); if(!name||name===old) return;
    const cc=ensureCharcos(S.artist); if(name in cc){ toast('이미 있음'); return; }
    cc[name]=cc[old]; delete cc[old]; S.ccCat=name; renderCharcos(); markDirty();
  });
}
function ccCatDel(){
  const cat=S.ccCat; if(!cat) return;
  if(!confirm('카테고리 삭제: '+cat+' ?')) return;
  const cc=ensureCharcos(S.artist); delete cc[cat];
  if(!Object.keys(cc).length) cc.Default=[];
  S.ccCat=''; renderCharcos(); markDirty();
}
function ccAddToCat(){
  const cat=S.ccCat||'Default'; const key=el('ccAdd').value.trim(); if(!key) return;
  const cc=ensureCharcos(S.artist); const lst=cc[cat]||(cc[cat]=[]);
  if(!lst.includes(key)) lst.push(key);
  renderCharcos(); markDirty();
}
function ccRemoveFromCat(){
  const cat=S.ccCat||'Default'; if(!ccSel) return;
  const cc=ensureCharcos(S.artist); const lst=cc[cat]||[];
  const i=lst.indexOf(ccSel); if(i>=0) lst.splice(i,1);
  ccSel=''; renderCharcos(); markDirty();
}

// ---------------- Solos ----------------
function soloAdd(){
  if(S.atype!=='characters') return;
  const k=S.artist; if(!k) return;
  if(!S.solos.includes(k)) S.solos.push(k);
  renderSolos(); generate();
}
function soloDel(){
  const keep=[];
  el('soloList').querySelectorAll('.it').forEach((d,i)=>{ if(!d.classList.contains('sel')) keep.push(S.solos[i]); });
  S.solos=keep; renderSolos(); generate();
}
function soloClear(){ S.solos=[]; renderSolos(); generate(); }

// ---------------- selection change handlers ----------------
function onAtype(){ S.atype=el('atype').value; S.artist=''; renderArtist(); renderCharcos(); generate(); }
function onArtist(){ S.artist=el('artist').value; renderCharcos(); generate(); }
function onSongCat(){ S.songCat=el('songCat').value; renderSong(); generate(); }
function onSong(){ S.song=el('song').value; generate(); }
function onCostumeCat(){ S.costumeCat=el('costumeCat').value; renderCostume(); generate(); }
function onCostume(){ S.costume=el('costume').value; generate(); }
function noCostume(){ S.costume=''; el('costume').value=''; generate(); }
function onRatio(){ S.ratio=el('ratio').value; generate(); }
function onVtype(){ S.vtype=el('vtype').value; generate(); }

// ---------------- ratios editor ----------------
function editRatios(){
  const cur=(DATA.settings.aspect_ratios||[]).join(', ');
  openForm('Aspect Ratios 편집',[{key:'r',label:'쉼표로 구분',type:'text'}],{r:cur},(v)=>{
    DATA.settings.aspect_ratios=(v.r||'').split(',').map(s=>s.trim()).filter(Boolean);
    renderRatios(); generate(); markDirty();
  });
}

// ---------------- CRUD: artist / song / costume / mod ----------------
function reassignCategory(mapObj, key, cat){
  // remove key from every list in mapObj, then add to cat's list
  for(const c of Object.keys(mapObj)){ if(Array.isArray(mapObj[c])){ const i=mapObj[c].indexOf(key); if(i>=0) mapObj[c].splice(i,1); } }
  if(cat && cat!=='(변경 안 함)'){ (mapObj[cat]=mapObj[cat]||[]).push(key); }
}
function currentCategoryOf(mapObj, key){
  for(const c of Object.keys(mapObj)){ if(Array.isArray(mapObj[c])&&mapObj[c].includes(key)) return c; }
  return '';
}

function crudArtist(op){
  const store=DATA[S.atype]; const isChar=S.atype==='characters';
  if(op==='del'){
    const k=S.artist; if(!k) return; if(!confirm('삭제: '+k+' ?')) return;
    delete store[k];
    if(isChar){ S.solos=S.solos.filter(x=>x!==k); delete (DATA.character_costume_categories||{})[k]; }
    S.artist=''; renderArtist(); renderCharcos(); renderSolos(); generate(); markDirty(); return;
  }
  const editing=op==='edit'; const k0=editing?S.artist:''; if(editing && !k0) return;
  const cur=editing?(store[k0]||{}):{};
  const fields=[];
  if(!editing) fields.push({key:'__key',label:'Key (고유 이름)',type:'text'});
  fields.push({key:'japanese',label:'japanese',type:'text'});
  fields.push({key:'korean',label:'korean',type:'text'});
  fields.push({key:'english',label:'english',type:'text'});
  fields.push({key:'artist_playlist',label:'Artist Playlist (URL)',type:'text'});
  fields.push({key:'hashtags',label:'Hashtags',type:'text'});
  const init=editing?Object.assign({},cur):{};
  openForm((editing?'편집: ':'추가: ')+(S.atype), fields, init, (v)=>{
    const key=editing?k0:(v.__key||'').trim(); if(!key) return;
    if(!editing && (key in store)){ toast('이미 있음'); return; }
    store[key]={japanese:v.japanese||'',korean:v.korean||'',english:v.english||'',
                artist_playlist:v.artist_playlist||'',hashtags:v.hashtags||''};
    S.artist=key; renderArtist(); renderCharcos(); generate(); markDirty();
  });
}

function crudSong(op){
  const store=DATA.songs; const cats=DATA.song_categories;
  if(op==='del'){
    const k=S.song; if(!k) return; if(!confirm('삭제: '+k+' ?')) return;
    delete store[k];
    for(const c of Object.keys(cats)){ const i=cats[c].indexOf(k); if(i>=0) cats[c].splice(i,1); }
    S.song=''; renderSong(); generate(); markDirty(); return;
  }
  const editing=op==='edit'; const k0=editing?S.song:''; if(editing && !k0) return;
  const cur=editing?(store[k0]||{}):{};
  const catOpts=['(변경 안 함)',...Object.keys(cats)];
  const fields=[];
  if(!editing) fields.push({key:'__key',label:'Key (고유 이름)',type:'text'});
  fields.push({key:'japanese',label:'japanese',type:'text'});
  fields.push({key:'korean',label:'korean',type:'text'});
  fields.push({key:'english',label:'english',type:'text'});
  fields.push({key:'__cat',label:'Category',type:'select',options:catOpts});
  const init=editing?Object.assign({__cat:currentCategoryOf(cats,k0)||'(변경 안 함)'},cur):{__cat:'(변경 안 함)'};
  openForm((editing?'편집: ':'추가: ')+'Song', fields, init, (v)=>{
    const key=editing?k0:(v.__key||'').trim(); if(!key) return;
    if(!editing && (key in store)){ toast('이미 있음'); return; }
    store[key]={japanese:v.japanese||'',korean:v.korean||'',english:v.english||''};
    if(v.__cat && v.__cat!=='(변경 안 함)') reassignCategory(cats,key,v.__cat);
    S.song=key; renderSongCat(); renderSong(); generate(); markDirty();
  });
}

function crudCostume(op){
  const store=DATA.costumes; const cats=DATA.costume_categories;
  if(op==='del'){
    const k=S.costume; if(!k) return; if(!confirm('삭제: '+k+' ?')) return;
    delete store[k];
    for(const c of Object.keys(cats)){ if(Array.isArray(cats[c])){ const i=cats[c].indexOf(k); if(i>=0) cats[c].splice(i,1); } }
    // also purge from every character_costume_categories list
    const ccc=DATA.character_costume_categories||{};
    for(const ch of Object.keys(ccc)){ for(const cc of Object.keys(ccc[ch]||{})){ const arr=ccc[ch][cc]; if(Array.isArray(arr)){ const i=arr.indexOf(k); if(i>=0) arr.splice(i,1); } } }
    S.costume=''; renderCostume(); renderCharcos(); generate(); markDirty(); return;
  }
  const editing=op==='edit'; const k0=editing?S.costume:''; if(editing && !k0) return;
  const cur=editing?(store[k0]||{}):{};
  const catOpts=['(변경 안 함)',...Object.keys(cats)];
  const fields=[];
  if(!editing) fields.push({key:'__key',label:'Key (고유 이름)',type:'text'});
  fields.push({key:'japanese',label:'japanese',type:'text'});
  fields.push({key:'korean',label:'korean',type:'text'});
  fields.push({key:'english',label:'english',type:'text'});
  fields.push({key:'costume_playlist',label:'Costume Playlist (URL)',type:'text'});
  fields.push({key:'__cat',label:'Category',type:'select',options:catOpts});
  const init=editing?Object.assign({__cat:currentCategoryOf(cats,k0)||'(변경 안 함)'},cur):{__cat:'(변경 안 함)'};
  openForm((editing?'편집: ':'추가: ')+'Costume', fields, init, (v)=>{
    const key=editing?k0:(v.__key||'').trim(); if(!key) return;
    if(!editing && (key in store)){ toast('이미 있음'); return; }
    store[key]={japanese:v.japanese||'',korean:v.korean||'',english:v.english||'',costume_playlist:v.costume_playlist||''};
    if(v.__cat && v.__cat!=='(변경 안 함)') reassignCategory(cats,key,v.__cat);
    S.costume=key; renderCostumeCat(); renderCostume(); generate(); markDirty();
  });
}

function crudMod(op){
  const store=DATA.mods;
  if(op!=='add'){
    if(!S.mods.length){ toast('먼저 mod를 체크하세요'); return; }
  }
  if(op==='del'){
    const k=S.mods[S.mods.length-1]; if(!confirm('삭제: '+k+' ?')) return;
    delete store[k]; S.mods=S.mods.filter(x=>x!==k); renderMods(); generate(); markDirty(); return;
  }
  const editing=op==='edit'; const k0=editing?S.mods[S.mods.length-1]:'';
  const cur=editing?(store[k0]||{}):{};
  const fields=[];
  if(!editing) fields.push({key:'__key',label:'Key (고유 이름)',type:'text'});
  fields.push({key:'japanese',label:'japanese',type:'text'});
  fields.push({key:'korean',label:'korean',type:'text'});
  fields.push({key:'english',label:'english',type:'text'});
  fields.push({key:'has_value',label:'값(value) 필드 사용',type:'checkbox'});
  fields.push({key:'default_value',label:'기본 값',type:'text'});
  const init=editing?Object.assign({},cur):{has_value:false};
  openForm((editing?'편집: ':'추가: ')+'Mod', fields, init, (v)=>{
    const key=editing?k0:(v.__key||'').trim(); if(!key) return;
    if(!editing && (key in store)){ toast('이미 있음'); return; }
    const mi={japanese:v.japanese||'',korean:v.korean||'',english:v.english||'',has_value:!!v.has_value};
    if(mi.has_value) mi.default_value=v.default_value||'';
    store[key]=mi; renderMods(); generate(); markDirty();
  });
}

// ---------------- generic modal form ----------------
function openForm(title, fields, init, onOk){
  const bg=document.createElement('div'); bg.className='modal-bg';
  const m=document.createElement('div'); m.className='modal';
  const h=document.createElement('h3'); h.textContent=title; m.appendChild(h);
  const inputs={};
  fields.forEach(f=>{
    const lab=document.createElement('label'); lab.textContent=f.label; m.appendChild(lab);
    if(f.type==='select'){
      const s=document.createElement('select'); (f.options||[]).forEach(o=>{ const op=document.createElement('option'); op.value=o; op.textContent=o; s.appendChild(op); });
      s.value=(init&&init[f.key]!=null)?init[f.key]:(f.options&&f.options[0]); inputs[f.key]=()=>s.value; m.appendChild(s);
    } else if(f.type==='checkbox'){
      const wrap=document.createElement('label'); wrap.className='chk';
      const c=document.createElement('input'); c.type='checkbox'; c.checked=!!(init&&init[f.key]);
      wrap.appendChild(c); wrap.appendChild(document.createTextNode(' '+f.label));
      lab.remove(); m.appendChild(wrap); inputs[f.key]=()=>c.checked;
    } else {
      const i=document.createElement('input'); i.type='text'; i.value=(init&&init[f.key]!=null)?init[f.key]:''; inputs[f.key]=()=>i.value; m.appendChild(i);
    }
  });
  const btns=document.createElement('div'); btns.className='btns';
  const cancel=document.createElement('button'); cancel.textContent='취소'; cancel.onclick=close;
  const ok=document.createElement('button'); ok.className='primary'; ok.textContent='확인';
  ok.onclick=()=>{ const out={}; for(const k in inputs) out[k]=inputs[k](); close(); onOk(out); };
  btns.appendChild(cancel); btns.appendChild(ok); m.appendChild(btns);
  bg.appendChild(m); el('modalRoot').appendChild(bg);
  bg.onclick=(e)=>{ if(e.target===bg) close(); };
  const first=m.querySelector('input,select'); if(first) first.focus();
  m.addEventListener('keydown',(e)=>{ if(e.key==='Enter'&&e.target.tagName!=='SELECT'){ ok.click(); } if(e.key==='Escape') close(); });
  function close(){ bg.remove(); }
}

// ---------------- import ----------------
function openImport(){
  const bg=document.createElement('div'); bg.className='modal-bg';
  const m=document.createElement('div'); m.className='modal'; m.style.maxWidth='620px';
  m.innerHTML='<h3>Import JSON values (비파괴 병합)</h3>'+
    '<div class="hint" style="margin-top:0">{"songs":{...}} 형태 전체, 또는 곧바로 songs 딕셔너리를 붙여넣으세요. 기존 값은 덮어쓰지 않습니다.</div>';
  const ta=document.createElement('textarea'); ta.placeholder='{ "songs": { "Song Name": {"japanese":"...","korean":"...","english":"..."} } }'; m.appendChild(ta);
  const btns=document.createElement('div'); btns.className='btns';
  const cancel=document.createElement('button'); cancel.textContent='취소'; cancel.onclick=()=>bg.remove();
  const imp=document.createElement('button'); imp.className='primary'; imp.textContent='Import';
  imp.onclick=async()=>{
    const text=ta.value.trim(); if(!text){ toast('내용이 없습니다'); return; }
    imp.disabled=true; imp.textContent='병합 중…';
    const j=await apiPost('/api/import',{text});
    if(j.ok){ DATA=j.data; renderAll(); bg.remove(); toast('Import 완료: '+(j.summary||'')); setStatus('저장됨 ✓','ok'); }
    else { imp.disabled=false; imp.textContent='Import'; toast('Import 실패: '+(j.error||'')); }
  };
  btns.appendChild(cancel); btns.appendChild(imp); m.appendChild(btns);
  bg.appendChild(m); el('modalRoot').appendChild(bg);
  bg.onclick=(e)=>{ if(e.target===bg) bg.remove(); };
  ta.focus();
}

// ---------------- copy ----------------
function copyOut(){
  const txt=el('preview').textContent||''; if(!txt){ toast('내용 없음'); return; }
  let ok=false;
  try{ const t=document.createElement('textarea'); t.value=txt; t.style.position='fixed'; t.style.opacity='0'; document.body.appendChild(t); t.focus(); t.select(); ok=document.execCommand('copy'); document.body.removeChild(t); }catch(e){}
  if(navigator.clipboard){ navigator.clipboard.writeText(txt).then(()=>{},()=>{}); ok=true; }
  toast(ok?'복사됨 ✓':'복사 실패 — 직접 선택하세요');
}

// ---------------- boot ----------------
function renderAll(){
  el('atype').value=S.atype;
  el('vtype').value=S.vtype;
  renderArtist(); renderSongCat(); renderSong(); renderCostumeCat(); renderCostume();
  renderRatios(); renderSolos(); renderMods(); renderFilter(); renderOrder(); renderFormats(); renderCharcos();
  generate();
}
async function boot(){
  const j=await apiGet('/api/data');
  DATA=j.data;
  if(DATA.settings && DATA.settings.aspect_ratios && DATA.settings.aspect_ratios.length) S.ratio=DATA.settings.aspect_ratios[0];
  renderAll();
  setStatus('불러옴 ✓ '+(j.path?('('+j.path.split(/[\\/]/).pop()+')'):''),'ok');
}
window.addEventListener('beforeunload',()=>{ if(saveTimer){ try{ navigator.sendBeacon('/api/save', new Blob([JSON.stringify({data:DATA})],{type:'application/json'})); }catch(e){} } });
boot();
</script></body></html>"""


# ==========================================================================
# Standalone app window (pywebview) + browser fallbacks (from sifas_fbx.py)
# ==========================================================================
def _pip(pkg):
    import subprocess
    for extra in (["--break-system-packages", "-q"], ["-q"]):
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", pkg] + extra, check=True)
            return True
        except Exception:
            pass
    return False


def _open_browser_window(url, width=1180, height=860):
    """Open `url` in a separate, sized window: a Chromium '--app' window if such a
    browser exists; else on macOS a new Safari window via AppleScript; else the
    default browser in a new window."""
    import subprocess
    import webbrowser
    cands = []
    if sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    elif sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                cands += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")]
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                     "microsoft-edge", "brave-browser"):
            p = shutil.which(name)
            if p:
                cands.append(p)
    exe = next((c for c in cands if c and os.path.isfile(c)), None)
    if exe:
        try:
            subprocess.Popen([exe, "--app=" + url, "--window-size=%d,%d" % (width, height)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    if sys.platform == "darwin":
        x, y = 120, 60
        script = ('tell application "Safari"\n'
                  '  activate\n'
                  '  make new document with properties {URL:"%s"}\n'
                  '  delay 0.3\n  try\n'
                  '    set bounds of front window to {%d, %d, %d, %d}\n'
                  '  end try\nend tell') % (url, x, y, x + width, y + height)
        try:
            r = subprocess.run(["osascript", "-e", script], timeout=90,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    try:
        webbrowser.open(url, new=1)
    except Exception:
        pass
    return False


def _try_app_window(url, server):
    """Show the UI in a standalone native app window (pywebview). Returns True if it
    ran the window (and stopped the server on close), False if pywebview isn't there."""
    import time
    try:
        import webview
    except Exception:
        print("[web] setting up the standalone app window (one-time install)...")
        try:
            _pip("pywebview")
            import webview
        except Exception:
            print("[web] (pywebview unavailable; opening a browser window instead)")
            return False
    try:
        webview.create_window("YouTube 설명 생성기", url, width=1180, height=860)
    except Exception:
        return False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webview.start()
    except Exception as ex:
        print("[web] couldn't open the app window (%s); opening a browser at %s" % (ex, url))
        _open_browser_window(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\n[web] stopped")
    try:
        server.shutdown()
    except Exception:
        pass
    return True


# ==========================================================================
# Web server (stdlib only)
# ==========================================================================
def run_web(data_path=DATA_FILE, open_browser=True, host="127.0.0.1", port=0, serve=True):
    import http.server
    import urllib.parse

    state = {"data": ensure_data(data_path), "path": os.path.abspath(data_path),
             "session_backup_done": False}
    lock = threading.Lock()

    def _save(data, do_backup):
        with lock:
            bak = None
            # First write of the session (or an explicit backup) rotates a numbered
            # restore point; subsequent autosaves are plain atomic writes (no spam).
            if do_backup or not state["session_backup_done"]:
                bak = rotate_numbered_backups(state["path"], 5)
                state["session_backup_done"] = True
            atomic_write_json(state["path"], data)
            state["data"] = data
            return bak

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _json_body(self):
            ln = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(ln) if ln else b""
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                return None

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/":
                return self._send(200, _WEB_PAGE, "text/html; charset=utf-8")
            if u.path == "/api/data":
                return self._send(200, json.dumps({"data": state["data"], "path": state["path"]}, ensure_ascii=False))
            if u.path == "/api/export":
                body = json.dumps(state["data"], ensure_ascii=False, indent=2)
                name = os.path.basename(state["path"]) or "youtube_data.json"
                return self._send(200, body, "application/json; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="%s"' % name})
            return self._send(404, "{}")

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/save":
                req = self._json_body()
                if not isinstance(req, dict) or not isinstance(req.get("data"), dict):
                    return self._send(400, json.dumps({"ok": False, "error": "bad data"}))
                try:
                    _save(req["data"], do_backup=False)
                    return self._send(200, json.dumps({"ok": True, "time": datetime.now().strftime("%H:%M:%S")}))
                except Exception as ex:
                    return self._send(200, json.dumps({"ok": False, "error": str(ex)}))
            if u.path == "/api/backup":
                try:
                    bak = rotate_numbered_backups(state["path"], 5)
                    state["session_backup_done"] = True
                    return self._send(200, json.dumps({"ok": bool(bak), "name": os.path.basename(bak) if bak else ""}))
                except Exception as ex:
                    return self._send(200, json.dumps({"ok": False, "error": str(ex)}))
            if u.path == "/api/import":
                req = self._json_body() or {}
                text = (req.get("text") or "").strip()
                if not text:
                    append_import_log(state["path"], "WARN", "Empty import content")
                    return self._send(200, json.dumps({"ok": False, "error": "empty"}))
                try:
                    obj = json.loads(text)
                except Exception as ex:
                    append_import_log(state["path"], "ERROR", "JSON parse failed", str(ex))
                    return self._send(200, json.dumps({"ok": False, "error": "JSON parse: " + str(ex)}))
                src = obj
                if isinstance(obj, dict) and "songs" not in obj and looks_like_songs_map(obj):
                    src = {"songs": obj}
                try:
                    src = normalize_data(src)
                except Exception:
                    pass
                try:
                    with lock:
                        rotate_numbered_backups(state["path"], 5)
                        state["session_backup_done"] = True
                        stats = merge_data_non_destructive(state["data"], src)
                        atomic_write_json(state["path"], state["data"])
                    added = (stats["songs_added"] + stats["groups_added"] + stats["characters_added"]
                             + stats["costumes_added"] + stats["mods_added"])
                    summary = "항목 +%d, 카테고리 +%d, 설정 +%d" % (
                        added,
                        stats["song_cat_updates"] + stats["costume_cat_updates"] + stats["char_costume_cat_updates"],
                        stats["settings_filled"])
                    append_import_log(state["path"], "INFO", "Import success", summary)
                    return self._send(200, json.dumps({"ok": True, "data": state["data"],
                                                        "stats": stats, "summary": summary}, ensure_ascii=False))
                except Exception as ex:
                    append_import_log(state["path"], "ERROR", "Merge/Save failed", str(ex))
                    return self._send(200, json.dumps({"ok": False, "error": str(ex)}))
            return self._send(404, "{}")

    server = http.server.ThreadingHTTPServer((host, port), H)
    if not serve:
        return server, state
    url = "http://%s:%d/" % (host, server.server_address[1])
    print("[web] YouTube 설명 생성기 UI:", url, "  (Ctrl-C to stop)")
    print("[web] data file:", state["path"])
    if open_browser and _try_app_window(url, server):
        return
    if open_browser:
        threading.Thread(target=_open_browser_window, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[web] stopped")
    finally:
        server.server_close()


# ==========================================================================
# Headless CLI helpers + selftest
# ==========================================================================
def cli_generate(a):
    data = ensure_data(a.data)
    sel = {
        "atype": a.atype,
        "artist": a.artist or "",
        "song": a.song or "",
        "costume": a.costume or "",
        "ratio": a.ratio or "",
        "vtype": a.vtype,
        "mods": [m.strip() for m in (a.mods or "").split(",") if m.strip()],
        "solos": [s.strip() for s in (a.solos or "").split(",") if s.strip()],
    }
    print(generate_description(data, sel))


def selftest():
    data = {
        "songs": {"S": {"japanese": "曲J", "korean": "곡K", "english": "SongE"}},
        "groups": {"G": {"japanese": "グG", "korean": "그G", "english": "GrpE",
                         "artist_playlist": "PL", "hashtags": "#g"}},
        "characters": {},
        "costumes": {"C": {"japanese": "衣", "korean": "의", "english": "Cos", "costume_playlist": "CPL"}},
        "mods": {"M": {"japanese": "モ", "korean": "모", "english": "ModE", "has_value": False}},
        "settings": {
            "languages": ["japanese", "korean", "english"],
            "format_order": ["{playlist}", "{japanese}", "{korean}", "{english}", "{hashtags}"],
            "japanese_format": "[スクスタ {type}] {song} ({artist}, {mod}, {costume}){ratio}",
            "korean_format": "[스쿠스타 {type}] {song} ({artist}, {mod}, {costume}){ratio}",
            "english_format": "[SIFAS {type}] {song} ({artist}, {mod}, {costume}){ratio}",
        },
    }
    sel = {"atype": "groups", "artist": "G", "song": "S", "costume": "C",
           "ratio": "16:9", "vtype": "MOD", "mods": ["M"], "solos": []}
    got = generate_description(data, sel)
    expect = (
        "G playlist : PL | Costume playlist : CPL\n"
        "[スクスタ MOD] 曲J (グG, モ, 衣衣装)[16:9]\n"
        "[스쿠스타 MOD] 곡K (그G, 모, 의 의상)[16:9]\n"
        "[SIFAS MOD] SongE (GrpE, ModE, Cos Costume)[16:9]\n"
        "#スクスタ #SIFAS #스쿠스타 #lovelive #ラブライブ #MOD #g"
    )
    ok = got == expect
    print("[selftest] generate_description:", "OK" if ok else "FAIL")
    if not ok:
        print("--- got ---\n" + got + "\n--- expected ---\n" + expect)

    # single-empty (costume empty, mod present) collapses cleanly
    sel2 = dict(sel, costume="")
    line2 = generate_description(data, sel2).split(chr(10))[1]
    ok2 = line2 == "[スクスタ MOD] 曲J (グG, モ)[16:9]"
    print("[selftest] single-empty cleanup:", "OK" if ok2 else "FAIL", "->", repr(line2))

    # both-empty (plain MV: no mod, no costume) -> no stray trailing comma
    sel2b = dict(sel, costume="", mods=[], vtype="MV")
    line2b = generate_description(data, sel2b).split(chr(10))[1]
    ok2b = line2b == "[スクスタ MV] 曲J (グG)[16:9]"
    print("[selftest] both-empty cleanup:", "OK" if ok2b else "FAIL", "->", repr(line2b))
    ok2 = ok2 and ok2b

    # merge is non-destructive
    dst = {"songs": {"S": {"japanese": "orig"}}}
    merge_data_non_destructive(dst, {"songs": {"S": {"japanese": "new", "korean": "k"}, "T": {"english": "T"}}})
    ok3 = dst["songs"]["S"]["japanese"] == "orig" and dst["songs"]["S"]["korean"] == "k" and "T" in dst["songs"]
    print("[selftest] merge non-destructive:", "OK" if ok3 else "FAIL")

    all_ok = ok and ok2 and ok3
    print("[selftest]", "ALL PASS" if all_ok else "SOME FAILED")
    return all_ok


# ==========================================================================
# main / argparse
# ==========================================================================
def build_parser():
    p = argparse.ArgumentParser(description="SIFAS/스쿠스타 YouTube 설명 생성기 (web UI).")
    p.add_argument("--web", action="store_true", help="launch the browser-based interface (default)")
    p.add_argument("--no-browser", action="store_true", help="serve only; don't open a window (headless/remote)")
    p.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=0, help="bind port (default: auto)")
    p.add_argument("--data", default=DATA_FILE, help="path to the data JSON (default: youtube_data.json)")
    sub = p.add_subparsers(dest="cmd")
    g = sub.add_parser("generate", help="print one description headlessly")
    g.add_argument("--data", default=DATA_FILE)
    g.add_argument("--atype", choices=["groups", "characters"], default="groups")
    g.add_argument("--artist", default="")
    g.add_argument("--song", default="")
    g.add_argument("--costume", default="")
    g.add_argument("--ratio", default="")
    g.add_argument("--vtype", choices=["MOD", "MV"], default="MOD")
    g.add_argument("--mods", default="", help="comma-separated mod keys")
    g.add_argument("--solos", default="", help="comma-separated character keys (for atype=characters)")
    sub.add_parser("selftest", help="check the generation logic")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    if a.cmd == "generate":
        cli_generate(a)
        return
    # default: web UI
    run_web(data_path=a.data, open_browser=not a.no_browser, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
