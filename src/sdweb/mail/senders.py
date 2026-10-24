"""Mail senders. send() raises on any failure; the worker retries."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from sdweb.config import WebSettings

log = logging.getLogger("sdweb.mail")

RESEND_URL = "https://api.resend.com/emails"


class Sender(Protocol):
    def send(self, to: str, subject: str, html: str, text: str) -> None: ...


class NullSender:
    """SD_MAIL_PROVIDER=none: mail is logged, not sent."""

    def send(self, to: str, subject: str, html: str, text: str) -> None:
        log.info("mail provider is none; not sending %r to %s", subject, to)


class ResendSender:
    def __init__(self, api_key: str, from_addr: str,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.from_addr = from_addr
        self.transport = transport

    def send(self, to: str, subject: str, html: str, text: str) -> None:
        with httpx.Client(transport=self.transport, timeout=20) as client:
            r = client.post(RESEND_URL, headers={"Authorization": f"Bearer {self.api_key}"},
                            json={"from": self.from_addr, "to": [to], "subject": subject,
                                  "html": html, "text": text})
            r.raise_for_status()


class SmtpSender:
    def __init__(self, host: str, port: int, user: str, password: str, starttls: bool,
                 from_addr: str) -> None:
        self.host, self.port, self.user, self.password = host, port, user, password
        self.starttls = starttls
        self.from_addr = from_addr

    def send(self, to: str, subject: str, html: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.from_addr, to, subject
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)


def sender_for(settings: WebSettings) -> Sender:
    if settings.mail_provider == "resend":
        return ResendSender(settings.resend_api_key, settings.mail_from)
    if settings.mail_provider == "smtp":
        return SmtpSender(settings.smtp_host, settings.smtp_port, settings.smtp_user,
                          settings.smtp_password, settings.smtp_starttls, settings.mail_from)
    return NullSender()
