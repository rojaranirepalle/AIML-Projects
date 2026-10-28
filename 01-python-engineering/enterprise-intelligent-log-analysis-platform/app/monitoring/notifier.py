"""Alert delivery: always logged; optionally emailed over SMTP (e.g. a Gmail app password)."""

import smtplib
import threading
from email.message import EmailMessage
from typing import Optional

from app.core.logger import logger
from app.monitoring.alerts import meets_severity
from app.parsers.template_miner import mask_text


class Notifier:
    def __init__(
        self,
        email_enabled: bool = False,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
        sender: Optional[str] = None,
        recipient: Optional[str] = None,
        min_severity: str = "high",
        app_name: str = "Log monitor",
    ) -> None:
        self.email_enabled = email_enabled and bool(recipient)
        self.smtp_host, self.smtp_port = smtp_host, smtp_port
        self.username, self.password = username, password
        self.sender = sender or username
        self.recipient = recipient
        self.min_severity = min_severity
        self.app_name = app_name

    @classmethod
    def from_settings(cls, settings) -> "Notifier":
        password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
        return cls(
            email_enabled=settings.alert_email_enabled,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            username=settings.smtp_username,
            password=password,
            sender=settings.alert_email_from,
            recipient=settings.alert_email_to,
            min_severity=settings.alert_email_min_severity,
            app_name=settings.app_name,
        )

    def notify(self, alert: dict) -> None:
        logger.warning("ALERT [%s] %s — %s", alert["severity"], alert["title"], alert.get("detail", ""))
        if self.email_enabled and meets_severity(alert, self.min_severity):
            # Never block the monitor loop on SMTP.
            threading.Thread(target=self._send_email, args=(alert,), daemon=True).start()

    def build_email(self, alert: dict) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = f"[{alert['severity'].upper()}] {alert['title']}"
        message["From"] = self.sender or self.recipient
        message["To"] = self.recipient
        message.set_content(
            f"{self.app_name} raised an alert.\n\n"
            f"Rule: {alert['rule']}\nSeverity: {alert['severity']}\nSource: {alert.get('source') or '-'}\n"
            f"Records: {alert.get('record_count', 1)}\nTime (UTC): {alert.get('created_at', '-')}\n\n"
            # Log text can carry customer data; mask it before it leaves the machine.
            f"{mask_text(alert.get('detail') or '')}\n"
        )
        return message

    def _send_email(self, alert: dict) -> None:
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(self.build_email(alert))
        except (OSError, smtplib.SMTPException) as error:
            logger.error("Alert email failed: %s", error)
