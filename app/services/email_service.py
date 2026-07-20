from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from fastapi.templating import Jinja2Templates

from app.core.config import settings

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=APP_DIR / "templates")


async def send_email(
    to_email: str,
    subject: str,
    plain_text: str,
    html_content: str | None = None,
) -> None:
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to_email
    message["Subject"] = subject

    message.set_content(plain_text)

    if html_content:
        message.add_alternative(html_content, subtype="html")

    await aiosmtplib.send(
        message,
        hostname=settings.mail_server,
        port=settings.mail_port,
        username=settings.mail_username if settings.mail_username else None,
        password=settings.mail_password.get_secret_value() or None,
        start_tls=settings.mail_use_tls,
    )


async def send_password_reset_email(to_email: str, username: str, token: str) -> None:
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"

    template = templates.env.get_template("email/password_reset.html")
    html_content = template.render(reset_url=reset_url, username=username)

    plain_text = f"""Hi {username},

You requested to reset your password. Click the link below to set a new password:

{reset_url}

This link will expire in {settings.reset_token_expire_minutes} minutes.

If you didn't request this, you can safely ignore this email.

Best regards,
The FastAPI Blog Team
"""

    await send_email(
        to_email=to_email,
        subject="Reset Your Password - FastAPI Blog",
        plain_text=plain_text,
        html_content=html_content,
    )


async def send_verification_email(to_email: str, username: str, token: str) -> None:
    verify_url = f"{settings.frontend_url}/verify-email?token={token}"

    template = templates.env.get_template("email/verify_email.html")
    html_content = template.render(verify_url=verify_url, username=username)

    plain_text = f"""Hi {username},

Welcome to FastAPI Blog! Please verify your email address by clicking the link below:

{verify_url}

This link will expire in {settings.email_verification_token_expire_hours} hours.

If you didn't create this account, you can safely ignore this email.

Best regards,
The FastAPI Blog Team
"""

    await send_email(
        to_email=to_email,
        subject="Verify Your Email - FastAPI Blog",
        plain_text=plain_text,
        html_content=html_content,
    )
