import os

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

def verification_email_template(name: str, token: str):
    verification_link = f"{FRONTEND_URL.rstrip('/')}/verify-email?token={token}"

    return f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px;">
        <h2 style="color: #f97316;">Welcome to TravelBNB!</h2>
        <p>Hi {name},</p>
        <p>Please verify your email:</p>

        <div style="text-align: center; margin: 30px 0;">
            <a href="{verification_link}" 
               style="background-color: #f97316; color: white; padding: 12px 24px; border-radius: 8px;">
               Verify Email
            </a>
        </div>

        <p>{verification_link}</p>
        <p style="font-size: 12px;">Expires in 24 hours</p>
    </div>
    """


def otp_email_template(otp: str, purpose: str):
    intro = "Use this OTP to continue."

    if purpose == "login":
        intro = "Use this OTP to login."

    return f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: auto;">
        <h2 style="color: #f97316;">TravelBNB OTP</h2>
        <p>{intro}</p>

        <div style="text-align: center;">
            <h1>{otp}</h1>
        </div>

        <p>Expires in 5 minutes</p>
    </div>
    """