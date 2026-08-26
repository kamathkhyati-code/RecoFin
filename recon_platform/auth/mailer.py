"""Password-reset email delivery via Resend's REST API.

Framework-agnostic like the rest of recon_platform/auth -- takes the API
key as a plain argument rather than reading st.secrets itself.
demo_app.py resolves RESEND_API_KEY from secrets and calls this.

Resend's free tier only delivers to the account's own verified address
until a sending domain is verified; that's a Resend account-level
constraint, not something this module can work around.
"""

from __future__ import annotations

import httpx

_RESEND_API_URL = "https://api.resend.com/emails"
_FROM_ADDRESS = "RecoFin <onboarding@resend.dev>"


class MailError(Exception):
    """Raised when the reset email fails to send. Callers should catch
    this and fall back to displaying the reset link/token directly
    rather than letting a mail-provider hiccup block password reset
    entirely."""


def send_password_reset_email(api_key: str, to_email: str, reset_link: str) -> None:
    body = (
        "You requested a password reset for your RecoFin account.\n\n"
        f"Reset your password here: {reset_link}\n\n"
        "This link expires in 30 minutes. If you didn't request this, "
        "you can ignore this email."
    )
    try:
        response = httpx.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": _FROM_ADDRESS,
                "to": [to_email],
                "subject": "Reset your RecoFin password",
                "text": body,
            },
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise MailError(f"Failed to send reset email: {e}") from e
