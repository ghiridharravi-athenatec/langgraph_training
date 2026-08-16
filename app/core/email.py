import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core import config
from app.core.logger import get_logger

logger = get_logger(__name__)


def send_email(to: str, subject: str, html_body: str, text_body: str = None) -> bool:
    '''Sends a single email via SMTP. Returns False (and logs) instead of raising on
    any failure - a transient mail-server outage or a missing SMTP_* config shouldn't
    surface as a 500 to a user who's just trying to reset their password; callers
    return the same generic response either way (see auth.py's forgot_password).'''
    if not config.SMTP_HOST or not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
        logger.warning(
            "SMTP not configured (SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD) - "
            "email to %s not sent: %r", to, subject,
        )
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.SMTP_FROM_EMAIL
    message["To"] = to
    if text_body:
        message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
            if config.SMTP_USE_TLS:
                server.starttls(context=ssl.create_default_context())
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.sendmail(message["From"], [to], message.as_string())
        logger.info("Sent email to %s: %r", to, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


def send_password_reset_email(to: str, reset_link: str) -> bool:
    subject = "Reset your password"
    expire_minutes = config.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    text_body = (
        "Someone requested a password reset for this account.\n\n"
        f"Reset your password: {reset_link}\n\n"
        f"This link expires in {expire_minutes} minutes. "
        "If you didn't request this, you can safely ignore this email."
    )
    html_body = f"""
    <p>Someone requested a password reset for this account.</p>
    <p><a href="{reset_link}">Reset your password</a></p>
    <p style="color:#73726c;font-size:13px;">
      This link expires in {expire_minutes} minutes. If you didn't request this,
      you can safely ignore this email.
    </p>
    """
    return send_email(to, subject, html_body, text_body)
