"""E-mail contents (French). Plain text and a minimal HTML alternative."""

from html import escape

from app.email.mailer import OutgoingEmail

_BRAND = "STREAMCLIP AI"


def _html(title: str, paragraphs: list[str], action: tuple[str, str] | None) -> str:
    body = "".join(f'<p style="margin:0 0 16px">{escape(p)}</p>' for p in paragraphs)
    button = ""
    if action:
        label, url = action
        button = (
            f'<p style="margin:24px 0"><a href="{escape(url, quote=True)}" '
            'style="background:#7c3aed;color:#ffffff;padding:12px 20px;border-radius:8px;'
            f'text-decoration:none;font-weight:600;display:inline-block">{escape(label)}</a></p>'
            '<p style="margin:0 0 16px;font-size:13px;color:#6b7280">Si le bouton ne fonctionne '
            f"pas, copiez ce lien dans votre navigateur :<br>{escape(url)}</p>"
        )
    return (
        '<!doctype html><html lang="fr"><body style="margin:0;padding:24px;background:#f4f4f5;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#18181b">'
        '<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;'
        'padding:32px">'
        f'<p style="margin:0 0 24px;font-weight:700;letter-spacing:.04em">{_BRAND}</p>'
        f'<h1 style="margin:0 0 16px;font-size:20px">{escape(title)}</h1>{body}{button}'
        '<p style="margin:24px 0 0;font-size:12px;color:#6b7280">Vous recevez cet e-mail car une '
        f"action a été demandée sur votre compte {_BRAND}.</p></div></body></html>"
    )


def _text(paragraphs: list[str], action: tuple[str, str] | None) -> str:
    lines = list(paragraphs)
    if action:
        lines.append(f"{action[0]} : {action[1]}")
    lines.append(f"— L'équipe {_BRAND}")
    return "\n\n".join(lines)


def _build(
    to: str, subject: str, title: str, paragraphs: list[str], action: tuple[str, str] | None = None
) -> OutgoingEmail:
    return OutgoingEmail(
        to=to,
        subject=subject,
        text=_text(paragraphs, action),
        html=_html(title, paragraphs, action),
    )


def verification_email(to: str, link: str, ttl_hours: int) -> OutgoingEmail:
    return _build(
        to,
        f"Confirmez votre adresse e-mail — {_BRAND}",
        "Confirmez votre adresse e-mail",
        [
            f"Bienvenue sur {_BRAND}. Confirmez votre adresse pour sécuriser votre compte.",
            f"Ce lien est valable {ttl_hours} heures et ne peut être utilisé qu'une fois.",
        ],
        ("Confirmer mon adresse", link),
    )


def password_reset_email(to: str, link: str, ttl_minutes: int) -> OutgoingEmail:
    return _build(
        to,
        f"Réinitialisation de votre mot de passe — {_BRAND}",
        "Réinitialisez votre mot de passe",
        [
            "Une réinitialisation de mot de passe a été demandée pour votre compte.",
            f"Ce lien est valable {ttl_minutes} minutes et ne peut être utilisé qu'une fois.",
            "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail : "
            "votre mot de passe reste inchangé.",
        ],
        ("Choisir un nouveau mot de passe", link),
    )


def password_changed_email(to: str) -> OutgoingEmail:
    return _build(
        to,
        f"Votre mot de passe a été modifié — {_BRAND}",
        "Mot de passe modifié",
        [
            "Le mot de passe de votre compte vient d'être modifié et vos autres sessions "
            "ont été déconnectées.",
            "Si vous n'êtes pas à l'origine de ce changement, réinitialisez immédiatement "
            "votre mot de passe depuis la page de connexion.",
        ],
    )
