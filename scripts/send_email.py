"""
Send the HTML email via Gmail SMTP using an App Password.
"""
from __future__ import annotations
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


def send(subject: str, html_body: str, settings: dict) -> None:
    cfg = settings["email"]
    to_addr = cfg["to"]
    from_addr = os.environ["GMAIL_FROM_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    from_name = cfg.get("from_name", "Flight Tracker")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    smtp_server = cfg.get("smtp_server", "smtp.gmail.com")
    smtp_port = int(cfg.get("smtp_port", 587))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(from_addr, password)
        server.sendmail(from_addr, to_addr, msg.as_string())

    log.info(f"Email sent to {to_addr}: {subject}")
