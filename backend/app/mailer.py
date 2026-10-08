import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings


def password_reset_delivery_configured() -> bool:
    return settings.app_env == "development" or bool(
        settings.smtp_host and settings.smtp_from_email
    )


def send_password_reset(email: str, token: str) -> None:
    if settings.app_env != "development":
        if not settings.smtp_host or not settings.smtp_from_email:
            raise RuntimeError(
                "Configure SMTP_HOST and SMTP_FROM_EMAIL "
                "to deliver password reset email"
            )

        message = EmailMessage()
        message["Subject"] = "Reset your GreenLit password"
        message["From"] = settings.smtp_from_email
        message["To"] = email
        reset_url = f"{settings.web_origin}/reset-password?token={token}"
        message.set_content(
            "Use this link to reset your GreenLit password within one hour:\n\n"
            f"{reset_url}\n"
        )
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return

    print(
        f"GreenLit password reset for {email}: "
        f"{settings.web_origin}/reset-password?token={token}"
    )
