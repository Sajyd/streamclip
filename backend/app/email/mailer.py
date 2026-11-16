"""Transactional e-mail delivery behind one interface.

Transports: `smtp` (any provider), `ses` (Amazon SES API), `console` (local
development only: prints the message), `none` (delivery not configured:
features that need e-mail report themselves as unavailable instead of
pretending a message was sent).
"""

import asyncio
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Protocol

import aiosmtplib
import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)


class EmailDeliveryDisabledError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str


class Mailer(Protocol):
    enabled: bool

    async def send(self, message: OutgoingEmail) -> None: ...


class DisabledMailer:
    enabled = False

    async def send(self, message: OutgoingEmail) -> None:
        raise EmailDeliveryDisabledError("E-mail delivery is not configured")


class ConsoleMailer:
    """Development only. Refused by the production configuration because the
    message body contains single-use secrets."""

    enabled = True

    async def send(self, message: OutgoingEmail) -> None:
        print(  # noqa: T201 - this transport's whole purpose
            f"\n--- e-mail to {message.to} ---\nSubject: {message.subject}\n\n{message.text}\n---\n"
        )


class SmtpMailer:
    enabled = True

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: OutgoingEmail) -> None:
        mime = EmailMessage()
        mime["From"] = self._settings.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        password = self._settings.smtp_password
        await aiosmtplib.send(
            mime,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.smtp_username,
            password=password.get_secret_value() if password else None,
            start_tls=self._settings.smtp_starttls,
            timeout=10,
        )


class SesMailer:
    enabled = True

    def __init__(self, settings: Settings) -> None:
        import boto3  # imported lazily: only needed for this transport

        access_key = settings.s3_access_key_id
        secret_key = settings.s3_secret_access_key
        self._client: Any = boto3.client(
            "sesv2",
            region_name=settings.ses_region or settings.s3_region,
            aws_access_key_id=access_key.get_secret_value() if access_key else None,
            aws_secret_access_key=secret_key.get_secret_value() if secret_key else None,
        )
        self._from = settings.email_from

    def _send(self, message: OutgoingEmail) -> None:
        self._client.send_email(
            FromEmailAddress=self._from,
            Destination={"ToAddresses": [message.to]},
            Content={
                "Simple": {
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": message.text, "Charset": "UTF-8"},
                        "Html": {"Data": message.html, "Charset": "UTF-8"},
                    },
                }
            },
        )

    async def send(self, message: OutgoingEmail) -> None:
        await asyncio.to_thread(self._send, message)


def _sender_is_valid(value: str) -> bool:
    address = parseaddr(value)[1]
    local, sep, domain = address.rpartition("@")
    return bool(sep and local and domain) and not any(c.isspace() for c in address)


def build_mailer(settings: Settings) -> Mailer:
    if settings.email_transport != "none" and not _sender_is_valid(settings.email_from):
        raise ValueError("EMAIL_FROM must contain a valid address")
    match settings.email_transport:
        case "smtp":
            return SmtpMailer(settings)
        case "ses":
            return SesMailer(settings)
        case "console":
            return ConsoleMailer()
        case _:
            return DisabledMailer()
