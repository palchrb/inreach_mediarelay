#!/usr/bin/env python3
import smtplib, os, mimetypes
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Optional

def _attach(msg: EmailMessage, p: Path):
    ctype, _ = mimetypes.guess_type(p.name)
    if not ctype: ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)
    msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)

def send_mail_ext(
    to_addrs: Iterable[str],
    subject: str,
    text_body: str,
    attachments: Optional[list[Path]] = None,
    headers: Optional[dict[str,str]] = None
):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    pw   = os.environ.get("SMTP_PASS")
    from_addr = os.environ.get("SMTP_FROM", user or "")
    use_tls = os.environ.get("SMTP_USE_TLS", "1") == "1"

    if not (host and port and user and pw and from_addr):
        raise RuntimeError("SMTP-konfig mangler: SMTP_HOST/PORT/USER/PASS/FROM")

    to_list = [a.strip() for a in to_addrs if a and a.strip()]
    if not to_list:
        raise RuntimeError("Ingen mottakere oppgitt.")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content(text_body)

    if headers:
        for k, v in headers.items():
            if k.lower() in {"from","to","subject"}: continue
            msg[k] = v

    for p in (attachments or []):
        _attach(msg, Path(p))

    with smtplib.SMTP(host, port) as s:
        s.ehlo()
        if use_tls: s.starttls(); s.ehlo()
        s.login(user, pw)
        s.send_message(msg)
