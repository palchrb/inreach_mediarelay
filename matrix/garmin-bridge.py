#!/usr/bin/env python3
import os, sys, json, time, base64, mimetypes, threading, queue, shutil, signal
import sqlite3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import subprocess

# -------- Config helpers --------
def env(name, default=None, cast=str):
    v = os.environ.get(name, default)
    if cast is int:
        try: return int(v)
        except: return int(default) if default is not None else 0
    if cast is float:
        try: return float(v)
        except: return float(default) if default is not None else 0.0
    return v

DB_PATH = env("DB_PATH")
ROOT_DIR = env("ROOT_DIR")
POLL_DB_SEC = env("POLL_DB_SEC", 1, int)
TAIL_LIMIT = env("TAIL_LIMIT", 200, int)
LAST_N_BOOT = env("LAST_N_BOOT", 5, int)
DEBUG = env("DEBUG", "1") == "1"
FORWARD_MODE = env("FORWARD_MODE", "base64")
DELETE_ON_SUCCESS = env("DELETE_ON_SUCCESS", "1") == "1"
DELETE_DELAY_SEC = env("DELETE_DELAY_SEC", 2, int)
CAPTION_TARGETING = env("CAPTION_TARGETING", "1") == "1"
TARGET_WORD_STRIP = env("TARGET_WORD_STRIP", "1") == "1"

PROVISION_BIND = env("PROVISION_BIND", "127.0.0.1")
PROVISION_PORT = env("PROVISION_PORT", 8788, int)
PROVISION_SECRET = env("PROVISION_SECRET", "")

STATE_DIR = env("STATE_DIR", "/var/lib/garmin-bridge")
SUBS_JSON = env("SUBS_JSON", os.path.join(STATE_DIR, "subs.json"))
SEEN_FILE = env("SEEN_FILE", os.path.join(STATE_DIR, "seen.txt"))

MEDIA_EXTS = [x.strip() for x in env("MEDIA_EXTS", "avif,jpg,jpeg,png,ogg,oga,mp4,m4a").split(",") if x.strip()]
HTTP_TIMEOUT_SEC = env("HTTP_TIMEOUT_SEC", 15, int)
RETRY_BACKOFFS = [int(x) for x in env("RETRY_BACKOFFS", "1,4,10").split(",") if x.strip()]

# Ensure state dirs
os.makedirs(STATE_DIR, exist_ok=True)

# -------- Logging --------
def ts(): return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
def log(*a, level="INFO"):
    if level=="DEBUG" and not DEBUG: return
    print(f"{ts()} [{level}]"," ".join(str(x) for x in a), flush=True)

# -------- State: subscriptions & seen --------
_sub_lock = threading.Lock()
def _load_subs():
    if not os.path.isfile(SUBS_JSON): return {}
    try:
        with open(SUBS_JSON,"r",encoding="utf-8") as f:
            return json.load(f) or {}
    except: return {}
def _save_subs(d):
    tmp=SUBS_JSON+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(d,f,ensure_ascii=False,indent=2)
    os.replace(tmp,SUBS_JSON)

# subs structure:
# { "msisdn": { "name_lower": { "name": "<name>", "status": "pending|active|inactive",
#                               "verify_code": "xxxx", "webhook_url": "...", "bearer_token": "...",
#                               "created_ts": 0, "updated_ts": 0 } } }
def subs_get(msisdn):
    with _sub_lock:
        subs = _load_subs()
        return subs.get(msisdn) or {}
def subs_set(msisdn, name, status, verify_code, url, token):
    now = int(time.time())
    nkey = name.lower()
    with _sub_lock:
        subs = _load_subs()
        ms = subs.get(msisdn) or {}
        # enforce uniqueness per msisdn
        if nkey in ms:
            # update existing
            ms[nkey].update({"status": status, "verify_code": verify_code, "webhook_url": url, "bearer_token": token, "updated_ts": now})
        else:
            # ensure no other entry with same normalized name
            ms[nkey] = {"name": name, "status": status, "verify_code": verify_code, "webhook_url": url, "bearer_token": token, "created_ts": now, "updated_ts": now}
        subs[msisdn]=ms
        _save_subs(subs)

def subs_check_name_exists(msisdn, name):
    nkey = name.lower()
    s = subs_get(msisdn)
    return nkey in s

def subs_activate_if_code(msisdn, name, code):
    nkey = name.lower()
    with _sub_lock:
        subs = _load_subs()
        ms = subs.get(msisdn) or {}
        row = ms.get(nkey)
        if not row: return False
        if str(row.get("verify_code","")) != str(code): return False
        row["status"]="active"; row["updated_ts"]=int(time.time())
        ms[nkey]=row; subs[msisdn]=ms; _save_subs(subs)
    return True

def subs_deactivate(msisdn, name=None):
    with _sub_lock:
        subs = _load_subs()
        ms = subs.get(msisdn) or {}
        changed=False
        if name:
            nkey=name.lower()
            if nkey in ms:
                ms[nkey]["status"]="inactive"; ms[nkey]["updated_ts"]=int(time.time()); changed=True
        else:
            for k in list(ms.keys()):
                ms[k]["status"]="inactive"; ms[k]["updated_ts"]=int(time.time()); changed=True
        if changed:
            subs[msisdn]=ms; _save_subs(subs)
    return

def active_targets(msisdn):
    ms = subs_get(msisdn)
    return [v for v in ms.values() if (v.get("status")=="active")]

# Seen IDs
_seen_lock = threading.Lock()
_seen = set()
def load_seen():
    global _seen
    if not os.path.isfile(SEEN_FILE): return
    try:
        with open(SEEN_FILE,"r") as f:
            _seen = set(x.strip() for x in f if x.strip())
    except: pass
def add_seen(key):
    with _seen_lock:
        _seen.add(key)
        with open(SEEN_FILE,"a") as f: f.write(key+"\n")
        # trim file if huge
        try:
            if os.path.getsize(SEEN_FILE) > 1024*1024:
                with open(SEEN_FILE,"r") as f: lines=[x for x in f][-5000:]
                with open(SEEN_FILE,"w") as f: f.writelines(lines)
        except: pass
def is_seen(key):
    with _seen_lock:
        return key in _seen

load_seen()

# -------- SQLite helpers --------
def db_conn():
    # read-only, shared cache, busy timeout
    uri = f"file:{DB_PATH}?mode=ro&cache=shared"
    con = sqlite3.connect(uri, uri=True, timeout=2.5, isolation_level=None, check_same_thread=False)
    try:
        con.execute("PRAGMA read_uncommitted=1;")
    except: pass
    return con

def fmt_local(s):
    try:
        s=int(s)
        if s>1_000_000_000_000: s=int(s/1000)
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s))
    except: return str(s)

def lookup_msisdn(con, thread_id):
    try:
        cur=con.execute("SELECT addresses FROM message_thread WHERE id=?", (thread_id,))
        r=cur.fetchone()
        return r[0] if r and r[0] else ""
    except: return ""

def iter_new_messages(con, last_id):
    # returns ascending > last_id limited
    q = """
    SELECT m.id, COALESCE(m.text,''), m.message_thread_id, m.sent_time, m.media_attachment_id
    FROM message m
    WHERE m.id > ?
    ORDER BY m.id ASC
    LIMIT ?
    """
    for row in con.execute(q,(last_id, TAIL_LIMIT)):
        yield row

def media_lookup(con, attach_id):
    # returns (media_type, file_id)
    q = """
    SELECT mr.media_type, COALESCE(mf.file_id,'')
    FROM media_attachment_record mr
    LEFT JOIN media_attachment_file mf ON mf.attachment_id = mr.attachment_id
    WHERE mr.attachment_id = ?
    ORDER BY IFNULL(mf.fileSize,0) DESC
    LIMIT 1
    """
    cur=con.execute(q,(attach_id,))
    r=cur.fetchone()
    if not r: return (None, "")
    return (r[0], r[1] or "")

# ---- CHANGED: try both file_id and attachment_id when resolving file path
def find_media_path(file_id, attach_id=None):
    ids = [x for x in [file_id, attach_id] if x]
    if not ids:
        return ""
    roots=[os.path.join(ROOT_DIR, x) for x in ("high","preview","low","audio")]
    for the_id in ids:
        for d in roots:
            for ext in MEDIA_EXTS:
                p=os.path.join(d, f"{the_id}.{ext}")
                if os.path.isfile(p):
                    return p
    return ""

# -------- HTTP client (stdlib) --------
import urllib.request, urllib.error
def http_post_json(url, data_dict, bearer=None, idem_key=None, timeout=HTTP_TIMEOUT_SEC):
    body = json.dumps(data_dict).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, method="POST")
    req.add_header("Content-Type","application/json")
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    if idem_key:
        req.add_header("Idempotency-Key", idem_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            return status, resp.read()
    except urllib.error.HTTPError as e:
        try: payload=e.read()
        except: payload=b""
        return e.code, payload
    except Exception as e:
        return None, str(e).encode()

# -------- Provision HTTP server --------
class ProvisionHandler(BaseHTTPRequestHandler):
    server_version = "GarminBridge/1.0"
    def _bad(self, code, msg):
        self.send_response(code); self.send_header("Content-Type","text/plain"); self.end_headers(); self.wfile.write(msg.encode())

    def do_POST(self):
        if self.path != "/provision":
            self._bad(404,"not_found"); return
        auth = self.headers.get("Authorization","")
        if not auth.lower().startswith("bearer ") or not PROVISION_SECRET or auth.split(" ",1)[1].strip()!=PROVISION_SECRET:
            self._bad(401,"bad_token"); return
        try:
            ln = int(self.headers.get("Content-Length","0"))
            raw = self.rfile.read(ln)
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._bad(400,"invalid_json"); return
        msisdn = (payload.get("msisdn") or "").strip()
        name = (payload.get("name") or "").strip()
        code = (payload.get("verify_code") or "").strip()
        wh = (payload.get("webhook_url") or "").strip()
        tok = (payload.get("bearer_token") or "").strip()
        if not (msisdn and name and code and wh and tok):
            self._bad(400,"missing_fields"); return
        # uniqueness per msisdn
        if subs_check_name_exists(msisdn, name):
            # update existing (rotate code/token/url) but keep uniqueness
            subs_set(msisdn, name, "pending", code, wh, tok)
            log(f"Provision update: {msisdn} name={name}")
            self.send_response(200); self.end_headers(); self.wfile.write(b"updated"); return
        subs_set(msisdn, name, "pending", code, wh, tok)
        log(f"Provision create: {msisdn} name={name}")
        self.send_response(201); self.end_headers(); self.wfile.write(b"created")

    def log_message(self, fmt, *args):
        if DEBUG:
            log("HTTP", fmt%args, level="DEBUG")
        return

def start_http():
    srv = ThreadingHTTPServer((PROVISION_BIND, PROVISION_PORT), ProvisionHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log(f"Provision HTTP listening on http://{PROVISION_BIND}:{PROVISION_PORT}")
    return srv

# -------- Caption targeting --------
def split_first_word(s):
    if not s: return ("","")
    s=s.strip()
    if not s: return ("","")
    parts=s.split(None,1)
    if len(parts)==1: return (parts[0], "")
    return (parts[0], parts[1])

# -------- Forwarding --------
def guess_mime(path):
    mt = mimetypes.guess_type(path)[0]
    return mt or "application/octet-stream"

def forward_media(msisdn, msg_id, attach_id, path, caption):
    tgs = active_targets(msisdn)
    if not tgs:
        log(f"No active subs for {msisdn}, skip media id={msg_id}", level="DEBUG")
        return

    # caption targeting
    targets = tgs
    out_caption = caption or ""
    if CAPTION_TARGETING and out_caption:
        first, rest = split_first_word(out_caption)
        if first:
            cand = [t for t in tgs if t.get("name","").lower()==first.lower()]
            if cand:
                targets = cand
                if TARGET_WORD_STRIP:
                    out_caption = rest

    # Prepare payload parts
    filename = os.path.basename(path)
    mimetype = guess_mime(path)
    idem_key = f"msg:{msg_id}:att:{attach_id}"

    # Build body per FORWARD_MODE
    def build_body():
        if FORWARD_MODE=="file_url":
            return {"filename": filename, "mimetype": mimetype, "url": f"file://{path}", "caption": out_caption}
        else:
            with open(path,"rb") as f: raw=f.read()
            b64 = base64.b64encode(raw).decode("ascii")
            return {"filename": filename, "mimetype": mimetype, "data_b64": b64, "caption": out_caption}

    body = build_body()

    # Send to each target with retry policy
    all_ok = True
    for tgt in targets:
        url = tgt.get("webhook_url","")
        tok = tgt.get("bearer_token","")
        masked_tok = (tok[:6]+"…") if tok else ""
        ok=False
        for attempt, backoff in enumerate([0]+RETRY_BACKOFFS):
            if attempt>0:
                time.sleep(backoff)
            status, resp = http_post_json(url, body, bearer=tok, idem_key=idem_key)
            if status is None:
                log(f"POST error (no status) to {url} tok={masked_tok} attempt={attempt} err={resp.decode(errors='ignore')}", level="DEBUG")
                continue
            if 200 <= int(status) < 300:
                log(f"POST {status} → {url} name={tgt.get('name')} msisdn={msisdn} id={msg_id}", level="INFO")
                ok=True
                break
            elif int(status) in (401,403):
                log(f"POST {status} (auth) → deactivate sub {tgt.get('name')} for {msisdn}", level="INFO")
                subs_deactivate(msisdn, tgt.get("name"))
                break
            elif int(status) == 409:
                log(f"POST 409 duplicate (idempotent) → {url}", level="DEBUG")
                ok=True
                break
            else:
                log(f"POST {status} to {url} attempt={attempt}", level="DEBUG")
        if not ok:
            all_ok=False

    if all_ok and DELETE_ON_SUCCESS:
        try:
            time.sleep(DELETE_DELAY_SEC)
            os.remove(path)
            log(f"Deleted media file {path}")
        except Exception as e:
            log(f"Delete failed {path}: {e}", level="DEBUG")

# -------- Command parsing (text) --------
def handle_text(msisdn, text):
    if not text: return
    t = (text or "").strip()
    low = t.lower()
    parts = low.split()
    if not parts: return
    if parts[0] == "sub":
        # forms: "sub <name> <code>"
        if len(parts) >= 3:
            name = parts[1]
            code = parts[2]
            ok = subs_activate_if_code(msisdn, name, code)
            if ok: log(f"Activated sub msisdn={msisdn} name={name}")
            else:  log(f"Sub verify failed msisdn={msisdn} name={name}", level="DEBUG")
        return
    if parts[0] == "unsub":
        if len(parts) >= 2:
            name = parts[1]
            subs_deactivate(msisdn, name)
            log(f"Unsub one msisdn={msisdn} name={name}")
        else:
            subs_deactivate(msisdn, None)
            log(f"Unsub ALL msisdn={msisdn}")
        return

# -------- Watcher loop --------
def bridge_loop(stop_evt):
    last_id = 0
    try:
        with db_conn() as con:
            cur=con.execute("SELECT IFNULL(MAX(id),0) FROM message;")
            row=cur.fetchone()
            last_id = int(row[0] or 0)
    except Exception as e:
        log(f"Init last_id failed: {e}", level="DEBUG")

    # Boot dump
    if LAST_N_BOOT>0:
        try:
            with db_conn() as con:
                q = f"""
                SELECT m.id, COALESCE(m.text,''), m.message_thread_id, m.sent_time, m.media_attachment_id
                FROM message m
                ORDER BY m.id DESC
                LIMIT ?
                """
                rows = list(con.execute(q,(LAST_N_BOOT,)))
                rows.reverse()
                for (mid, text, thread, sent, media_attach) in rows:
                    msisdn = lookup_msisdn(con, thread)
                    if media_attach:
                        mtype, fid = media_lookup(con, media_attach)
                        attach = str(media_attach)
                        if not fid:
                            log(f"No file_id yet for attach={attach}; will try attachment_id on disk", level="DEBUG")
                        path = find_media_path(fid, attach)
                        if not path:
                            log(f"File not found yet for attach={attach} (fid={fid or '∅'})", level="DEBUG")
                        log(f"[BOOT] [MEDIA] id={mid} msisdn={msisdn} caption=\"{text}\" attach={attach} file=\"{path}\" sent_s={sent} sent_local=\"{fmt_local(sent)}\"")
                    else:
                        log(f"[BOOT] [TEXT] id={mid} msisdn={msisdn} thread={thread} text=\"{text}\" sent_s={sent} sent_local=\"{fmt_local(sent)}\"")
        except Exception as e:
            log(f"Boot dump failed: {e}", level="DEBUG")

    log(f"[watch] Bridge running: poll DB every {POLL_DB_SEC}s (tail {TAIL_LIMIT}).")
    pending_media = {}  # attach_id -> (msisdn, mid, caption, fid)

    while not stop_evt.is_set():
        try:
            with db_conn() as con:
                for (mid, text, thread, sent, media_attach) in iter_new_messages(con, last_id):
                    last_id = max(last_id, int(mid))
                    msisdn = lookup_msisdn(con, thread)
                    key=f"msg:{mid}"
                    if media_attach:
                        mtype, fid = media_lookup(con, media_attach)
                        attach = str(media_attach)
                        if not fid:
                            log(f"No file_id yet for attach={attach}; will try attachment_id on disk", level="DEBUG")
                        path = find_media_path(fid, attach)
                        if not path:
                            log(f"[WAIT] file not present yet for attach={attach} (fid={fid or '∅'})", level="DEBUG")
                        log(f"[MEDIA] id={mid} msisdn={msisdn} caption=\"{text}\" attach={attach} file=\"{path}\" sent_s={sent} sent_local=\"{fmt_local(sent)}\"", level="DEBUG")
                        pending_media[attach]=(msisdn, mid, text, fid)
                        # if file exists already → forward now
                        if path:
                            if not is_seen(key):
                                forward_media(msisdn, mid, attach, path, text)
                                add_seen(key)
                    else:
                        log(f"[TEXT] id={mid} msisdn={msisdn} text=\"{text}\" sent_s={sent} sent_local=\"{fmt_local(sent)}\"", level="DEBUG")
                        handle_text(msisdn, text)

                # Re-scan pending for files that appeared
                for attach,(msisdn, mid, text, fid) in list(pending_media.items()):
                    path = find_media_path(fid, attach)
                    if path:
                        key=f"msg:{mid}"
                        if not is_seen(key):
                            forward_media(msisdn, mid, attach, path, text)
                            add_seen(key)
                        pending_media.pop(attach, None)

        except Exception as e:
            log(f"Loop error: {e}", level="DEBUG")

        stop_evt.wait(POLL_DB_SEC)

# -------- Main --------
def main():
    if not DB_PATH or not os.path.isfile(DB_PATH):
        log(f"DB not found: {DB_PATH}", level="ERROR"); sys.exit(1)
    if not ROOT_DIR or not os.path.isdir(ROOT_DIR):
        log(f"ROOT_DIR not found: {ROOT_DIR}", level="ERROR"); sys.exit(1)
    if not PROVISION_SECRET or len(PROVISION_SECRET) < 16:
        log("Weak or missing PROVISION_SECRET — set a strong value!", level="ERROR")

    srv = start_http()

    stop_evt = threading.Event()
    t = threading.Thread(target=bridge_loop, args=(stop_evt,), daemon=True)
    t.start()

    def _sig(signum, frame):
        log(f"Signal {signum} → shutting down")
        stop_evt.set()
        try: srv.shutdown()
        except: pass
        sys.exit(0)
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    # Wait forever
    while True:
        time.sleep(3600)

if __name__=="__main__":
    main()
