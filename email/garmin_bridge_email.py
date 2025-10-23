#!/usr/bin/env python3
import os, sys, time, sqlite3, re, threading
from pathlib import Path
from typing import Optional, List
from garmin_sender import send_mail_ext

# --- ENV ---
def env(name, default=None, cast=str):
    v = os.environ.get(name, default)
    if cast is int:
        try: return int(v)
        except: return int(default) if default is not None else 0
    return v

DB_PATH       = env("DB_PATH")
ROOT_DIR      = env("ROOT_DIR")
STATE_DIR     = env("STATE_DIR", "/var/lib/garmin-email-bridge")
POLL_DB_SEC   = env("POLL_DB_SEC", 1, int)
TAIL_LIMIT    = env("TAIL_LIMIT", 200, int)
LAST_N_BOOT   = env("LAST_N_BOOT", 5, int)
DEBUG         = os.environ.get("DEBUG","1") == "1"
MAX_ATTACH_MB = env("MAX_ATTACH_MB", 5, int)

USE_FIXED_RECIPIENTS = os.environ.get("USE_FIXED_RECIPIENTS","0") == "1"
# Comma-separated env -> list
FIXED_RECIPIENTS = [x.strip() for x in os.environ.get("FIXED_RECIPIENTS","").split(",") if x.strip()]

MAP_ZOOM  = env("MAP_ZOOM", 14, int)
MAP_LAYER = os.environ.get("MAP_LAYER","P")  # OpenTopoMap layer = P

SEEN_FILE = os.path.join(STATE_DIR, "seen.txt")
os.makedirs(STATE_DIR, exist_ok=True)

# --- Logging ---
def log(*a, level="INFO"):
    if level=="DEBUG" and not DEBUG: return
    print(time.strftime("%F %T"), f"[{level}]", *a, flush=True)

# --- Seen/idempotence (avoid double-sends per message id) ---
_seen_lock = threading.Lock()
_seen = set()
def load_seen():
    global _seen
    if not os.path.isfile(SEEN_FILE): return
    try:
        with open(SEEN_FILE,"r") as f: _seen = set(x.strip() for x in f if x.strip())
    except: pass
def is_seen(key:str)->bool:
    with _seen_lock: return key in _seen
def add_seen(key:str):
    with _seen_lock:
        _seen.add(key)
        with open(SEEN_FILE,"a") as f: f.write(key+"\n")
load_seen()

# --- DB helpers ---
def db_conn():
    # Read-only & shared cache
    uri = f"file:{DB_PATH}?mode=ro&cache=shared"
    con = sqlite3.connect(uri, uri=True, timeout=2.5)
    con.row_factory = sqlite3.Row
    try: con.execute("PRAGMA read_uncommitted=1;")
    except: pass
    return con

def fmt_local(ts_int):
    try:
        s=int(ts_int)
        if s>1_000_000_000_000: s//=1000
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s))
    except: return str(ts_int)

# We purposefully look up media by ATTACHMENT ID ONLY (this is what is present on disk)
MEDIA_EXTS = ("avif","jpg","jpeg","png","ogg","oga","mp4","m4a")
SEARCH_ROOTS = ("high","preview","low","audio","")

def find_media_by_attachment(root_dir:str, attach_id:str)->Optional[str]:
    if not attach_id: return None
    for sub in SEARCH_ROOTS:
        d = os.path.join(root_dir, sub)
        for ext in MEDIA_EXTS:
            p = os.path.join(d, f"{attach_id}.{ext}")
            if os.path.isfile(p):
                return p
    return None

# --- Email parsing ---
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

def parse_recipients_and_body(caption: str) -> tuple[List[str], str]:
    """
    Accept multiple recipients at the very start, separated by comma/semicolon,
    with optional spaces (e.g. 'a@x.com, b@y.io; c@z.net rest...').
    Also supports an optional 'mailto:' prefix.
    Returns (recipients, rest_of_caption). If no valid recipient list at the start,
    returns ([], original_caption).
    """
    if not caption:
        return ([], "")
    s = caption.strip()
    if not s:
        return ([], "")

    # Match from the beginning: one or more emails separated by , or ; (spaces allowed),
    # then capture the rest of the caption.
    m = re.match(
        r"^(?:mailto:)?\s*(?P<elist>(?:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\s*[;,]\s*)*"
        r"(?:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}))\s*(?P<rest>.*)$",
        s
    )
    if not m:
        return ([], s)

    elist = m.group("elist") or ""
    rest = m.group("rest") or ""
    emails = [e.strip().rstrip(",;:") for e in re.split(r"[;,]", elist) if e.strip()]

    # Validate all
    if not emails or not all(EMAIL_RE.match(e) for e in emails):
        return ([], s)

    return (emails, rest.strip())


# --- Map link ---
def build_osm_url(lat: float, lon: float, zoom: int = MAP_ZOOM, layer: str = MAP_LAYER) -> str:
    return (f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}"
            f"#map={zoom}/{lat:.6f}/{lon:.6f}&layers={layer}")

def size_mb(path:str)->float:
    try: return os.path.getsize(path)/(1024*1024)
    except: return 0.0

# --- Compose & send one media email ---
def send_media_email(msisdn:str, mid:int, attach_id:str, path:str,
                     caption:str, sent:int, thread_id:int,
                     lat:Optional[float], lon:Optional[float], alt:Optional[float]):
    # Resolve recipients
    if USE_FIXED_RECIPIENTS:
        recipients = FIXED_RECIPIENTS[:]
        body_caption = (caption or "").strip()
    else:
        recips, rest = parse_recipients_and_body(caption or "")
        if not recips:
            log(f"SKIP mid={mid}: caption must start with recipient email(s). caption={caption!r}", level="INFO")
            return
        recipients = recips
        body_caption = rest

    # Subject
    filename = os.path.basename(path)
    sent_local = fmt_local(sent)
    subject = f"[InReach] {msisdn} • {sent_local} • {filename}"

    # Body
    lines = []
    lines.append(f"From: {msisdn or '(unknown)'}")
    lines.append(f"Caption: {body_caption or '(empty)'}")
    if lat is not None and lon is not None:
        lines.append(f"Location: {lat:.6f}, {lon:.6f}")
        lines.append(f"Map: {build_osm_url(lat, lon)}")
    if alt is not None:
        lines.append(f"Altitude: {alt:.1f} m")
    lines.append(f"Sent: {sent_local}")
    lines.append(f"Message ID: {mid}")
    lines.append(f"Attachment: {filename}")
    # Optional warning about multi-attachment behavior
    lines.append("Note: Garmin Messenger may delay secondary attachments. Send one file per message for best results.")
    body = "\n".join(lines)

    # Threading headers
    domain = (os.environ.get("SMTP_FROM","") or "local").split("@")[-1]
    headers = {
        "Message-ID":  f"<inreach-{mid}-{attach_id}@{domain}>",
        "In-Reply-To": f"<inreach-thread-{thread_id}@{domain}>",
        "References":  f"<inreach-thread-{thread_id}@{domain}>",
    }

    # Size guard
    mb = size_mb(path)
    if MAX_ATTACH_MB and mb > float(MAX_ATTACH_MB):
        log(f"SKIP (too big) mid={mid} file={filename} size={mb:.2f}MB > {MAX_ATTACH_MB}MB", level="INFO")
        return

    # Send
    try:
        send_mail_ext(recipients, subject, body, attachments=[Path(path)], headers=headers)
        log(f"SENT ok → {','.join(recipients)} mid={mid} file={filename} size={mb:.2f}MB", level="INFO")
    except Exception as e:
        log(f"SEND FAIL mid={mid}: {e}", level="INFO")

# --- Lookup helpers ---
def lookup_msisdn(con, thread_id):
    try:
        r=con.execute("SELECT addresses FROM message_thread WHERE id=?", (thread_id,)).fetchone()
        return r[0] if r and r[0] else ""
    except: return ""

# --- Watch loop (no batching; light pending re-scan) ---
def bridge_loop():
    # Initialize last_id to current max
    last_id = 0
    with db_conn() as con:
        r = con.execute("SELECT IFNULL(MAX(id),0) AS maxid FROM message;").fetchone()
        last_id = int(r["maxid"] or 0)

    # Boot dump
    if LAST_N_BOOT>0:
        with db_conn() as con:
            rows = con.execute("""
                SELECT id, text, message_thread_id, sent_time, media_attachment_id,
                       latitude, longitude, altitude
                FROM message ORDER BY id DESC LIMIT ?
            """,(LAST_N_BOOT,)).fetchall()
            for r in reversed(rows):
                log(f"[BOOT] id={r['id']} media={bool(r['media_attachment_id'])} caption={r['text']!r}", level="DEBUG")

    log(f"[watch] poll={POLL_DB_SEC}s tail={TAIL_LIMIT} fixed={USE_FIXED_RECIPIENTS} recipients={FIXED_RECIPIENTS}", level="INFO")

    # pending: attach_id -> sqlite row
    pending = {}

    while True:
        try:
            with db_conn() as con:
                cur = con.execute("""
                    SELECT id, text, message_thread_id, sent_time, media_attachment_id,
                           latitude, longitude, altitude
                    FROM message
                    WHERE id > ?
                    ORDER BY id ASC
                    LIMIT ?
                """,(last_id, TAIL_LIMIT))

                for r in cur:
                    last_id = max(last_id, int(r["id"]))
                    mid = r["id"]
                    key = f"msg:{mid}"

                    if not r["media_attachment_id"]:
                        log(f"[TEXT] id={mid} (no media) — skip", level="DEBUG")
                        continue

                    attach = str(r["media_attachment_id"])
                    path = find_media_by_attachment(ROOT_DIR, attach)

                    if not path:
                        pending[attach] = r
                        log(f"[WAIT] file not ready attach={attach}", level="DEBUG")
                        continue

                    if is_seen(key):
                        continue

                    send_media_email(
                        msisdn = lookup_msisdn(con, r["message_thread_id"]),
                        mid = mid,
                        attach_id = attach,
                        path = path,
                        caption = r["text"] or "",
                        sent = r["sent_time"],
                        thread_id = r["message_thread_id"],
                        lat = r["latitude"],
                        lon = r["longitude"],
                        alt = r["altitude"]
                    )
                    add_seen(key)

                # Light re-scan of pendings each loop (no backoff complexity)
                for attach, row in list(pending.items()):
                    pth = find_media_by_attachment(ROOT_DIR, attach)
                    if pth:
                        key=f"msg:{row['id']}"
                        if not is_seen(key):
                            send_media_email(
                                msisdn = lookup_msisdn(con, row["message_thread_id"]),
                                mid = row["id"],
                                attach_id = attach,
                                path = pth,
                                caption = row["text"] or "",
                                sent = row["sent_time"],
                                thread_id = row["message_thread_id"],
                                lat = row["latitude"],
                                lon = row["longitude"],
                                alt = row["altitude"]
                            )
                            add_seen(key)
                        pending.pop(attach, None)

        except Exception as e:
            log(f"Loop error: {e}", level="DEBUG")

        time.sleep(POLL_DB_SEC)

def main():
    if not DB_PATH or not os.path.isfile(DB_PATH): sys.exit(f"DB not found: {DB_PATH}")
    if not ROOT_DIR or not os.path.isdir(ROOT_DIR): sys.exit(f"ROOT_DIR not found: {ROOT_DIR}")
    bridge_loop()

if __name__=="__main__":
    main()
