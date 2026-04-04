import resend
import os
from app.utils.email_template import verification_email_template, otp_email_template

resend.api_key = os.getenv("RESEND_API_KEY")

RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
RESEND_FROM_NAME = os.getenv("RESEND_FROM_NAME", "TravelBNB")


def send_email(to_email: str, subject: str, html: str):
    if not os.getenv("RESEND_API_KEY"):
        print("Email Error: RESEND_API_KEY is not configured")
        return None

    try:
        return resend.Emails.send({
            "from": f"{RESEND_FROM_NAME} <{RESEND_FROM_EMAIL}>",
            "to": [to_email],
            "subject": subject,
            "html": html
        })
    except Exception as e:
        print(f"Email Error: {e}")
        return None


def send_verification_email(to_email: str, name: str, token: str):
    html = verification_email_template(name, token)

    return send_email(
        to_email,
        "Verify your TravelBNB account",
        html
    )


def send_otp_email(to_email: str, otp: str, purpose="verification"):
    html = otp_email_template(otp, purpose)

    return send_email(
        to_email,
        "Your TravelBNB OTP Code",
        html
    )
