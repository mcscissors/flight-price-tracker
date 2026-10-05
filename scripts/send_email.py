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
    """Send HTML email via Gmail SMTP. Raises exception on failure with clear message."""
    try:
        cfg = settings["email"]
        to_addr = cfg["to"]
        from_addr = os.environ["GMAIL_FROM_ADDRESS"]
        password = os.environ["GMAIL_APP_PASSWORD"]
        from_name = cfg.get("from_name", "Flight Tracker")
    except KeyError as e:
        raise ValueError(f"Missing email config: {e}") from e

    try:
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

        log.info(f"✅ Email sent to {to_addr}: {subject}")
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("Gmail authentication failed. Check GMAIL_APP_PASSWORD.") from None
    except smtplib.SMTPException as e:
        raise RuntimeError(f"Gmail SMTP error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Email send failed: {e}") from e
