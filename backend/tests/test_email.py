"""E-mail transports and templates. SMTP is exercised against a real local server."""

import socket
from email import message_from_bytes, policy
from typing import Any

import pytest
from aiosmtpd.controller import Controller

from app.core.config import Settings
from app.email import templates
from app.email.mailer import (
    ConsoleMailer,
    DisabledMailer,
    EmailDeliveryDisabledError,
    SmtpMailer,
    build_mailer,
)


class _Inbox:
    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    async def handle_DATA(self, _server: Any, _session: Any, envelope: Any) -> str:
        self.envelopes.append(envelope)
        return "250 Message accepted"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def test_smtp_transport_delivers_a_multipart_message(settings: Settings) -> None:
    inbox, port = _Inbox(), _free_port()
    server = Controller(inbox, hostname="127.0.0.1", port=port)
    server.start()
    try:
        mailer = SmtpMailer(
            settings.model_copy(
                update={
                    "smtp_host": "127.0.0.1",
                    "smtp_port": port,
                    "email_from": "STREAMCLIP AI <no-reply@streamclip.test>",
                }
            )
        )
        link = "https://app.test/verify-email?token=abc_DEF-123&utm=a"
        await mailer.send(templates.verification_email("lea@example.com", link, 48))
    finally:
        server.stop()

    assert len(inbox.envelopes) == 1
    envelope = inbox.envelopes[0]
    assert envelope.mail_from == "no-reply@streamclip.test"
    assert envelope.rcpt_tos == ["lea@example.com"]
    message = message_from_bytes(envelope.content, policy=policy.default)
    assert message["Subject"] == "Confirmez votre adresse e-mail — STREAMCLIP AI"
    assert message["To"] == "lea@example.com"
    text = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    assert text is not None and html is not None
    assert link in text.get_content()
    assert "valable 48 heures" in text.get_content()
    # In HTML the link is escaped, once in the button and once as visible text.
    assert html.get_content().count("token=abc_DEF-123&amp;utm=a") == 2


async def test_smtp_failure_is_raised_so_the_queue_can_retry(settings: Settings) -> None:
    mailer = SmtpMailer(
        settings.model_copy(update={"smtp_host": "127.0.0.1", "smtp_port": _free_port()})
    )
    with pytest.raises(Exception):  # noqa: B017, PT011 - any transport error must propagate
        await mailer.send(templates.password_changed_email("lea@example.com"))


async def test_transport_selection(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    def configured(transport: str, **extra: Any) -> Settings:
        return settings.model_copy(update={"email_transport": transport, **extra})

    disabled = build_mailer(configured("none"))
    assert isinstance(disabled, DisabledMailer) and disabled.enabled is False
    with pytest.raises(EmailDeliveryDisabledError):  # never pretends a message was sent
        await disabled.send(templates.password_changed_email("lea@example.com"))

    assert isinstance(build_mailer(configured("smtp")), SmtpMailer)
    console = build_mailer(configured("console"))
    assert isinstance(console, ConsoleMailer)
    await console.send(templates.password_reset_email("lea@example.com", "https://x/r?token=t", 60))
    assert "https://x/r?token=t" in capsys.readouterr().out

    with pytest.raises(ValueError, match="EMAIL_FROM"):
        build_mailer(configured("smtp", email_from="not an address"))


def test_templates_escape_html_and_keep_plain_text_readable() -> None:
    message = templates.password_reset_email(
        "lea@example.com", 'https://app.test/reset?token=a&b="<script>"', 60
    )
    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html
    assert 'https://app.test/reset?token=a&b="<script>"' in message.text
    assert "60 minutes" in message.text and message.subject.startswith("Réinitialisation")
    changed = templates.password_changed_email("lea@example.com")
    assert "<a href" not in changed.html  # an information-only message carries no link
