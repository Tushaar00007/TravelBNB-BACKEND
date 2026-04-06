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


def promotional_email_template(message: str, cta_link: str = None):
    """
    Standard TravelBNB promotional template with branding and optional CTA.
    """
    # Simple newline to <br> conversion for rich-text-like behavior in textarea
    formatted_message = message.replace("\n", "<br>")
    
    cta_html = ""
    if cta_link:
        cta_html = f"""
        <div style="text-align: center; margin: 40px 0;">
            <a href="{cta_link}" 
               style="background-color: #f97316; color: white; padding: 16px 32px; border-radius: 12px; font-weight: 800; text-decoration: none; display: inline-block; box-shadow: 0 4px 12px rgba(249, 115, 22, 0.2);">
               Get Started
            </a>
        </div>
        """

    return f"""
    <div style="font-family: sans-serif; background-color: #f8fafc; padding: 40px 20px; line-height: 1.6;">
        <div style="max-width: 600px; margin: auto; background-color: white; border-radius: 24px; overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
            <div style="background-color: #ffffff; padding: 30px; text-align: center; border-bottom: 1px solid #f1f5f9;">
                <span style="font-size: 24px; font-weight: 900; color: #0f172a;">
                    Travel<span style="color: #f97316;">BNB</span>
                </span>
            </div>

            <div style="padding: 40px; color: #334155; line-height: 1.8; font-size: 16px;">
                {formatted_message}
                {cta_html}
            </div>

            <div style="background-color: #f8fafc; padding: 30px; text-align: center; color: #94a3b8; font-size: 12px; border-top: 1px solid #f1f5f9;">
                <p style="margin: 0;">&copy; 2026 TravelBNB. All rights reserved.</p>
                <p style="margin: 8px 0;">You're receiving this because you signed up for TravelBNB promotions.</p>
                <p style="margin: 0;">
                    <a href="#" style="color: #64748b; text-decoration: underline;">Unsubscribe</a> | 
                    <a href="#" style="color: #64748b; text-decoration: underline;">Contact Support</a>
                </p>
            </div>
        </div>
    </div>
    """


def password_reset_email_template(name: str, token: str):
    reset_link = f"{FRONTEND_URL.rstrip('/')}/reset-password?token={token}"

    return f"""
    <div style="font-family: sans-serif; background-color: #f8fafc; padding: 40px 20px; line-height: 1.6;">
        <div style="max-width: 500px; margin: auto; background-color: white; border-radius: 24px; overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
            <div style="padding: 40px; text-align: center;">
                <div style="margin-bottom: 24px;">
                    <span style="font-size: 24px; font-weight: 900; color: #0f172a;">
                        Travel<span style="color: #f97316;">BNB</span>
                    </span>
                </div>

                <h1 style="color: #0f172a; font-size: 20px; font-weight: 800; margin-bottom: 12px;">Reset your password</h1>
                <p style="color: #111; font-size: 15px; margin-bottom: 32px;">
                    Hi {name},<br>
                    You requested a password reset for your TravelBNB account.
                </p>

                <a href="{reset_link}" 
                   style="background-color: #f97316; color: white; padding: 12px 24px; border-radius: 12px; font-weight: 700; text-decoration: none; display: inline-block;">
                   Reset Password
                </a>

                <p style="color: #94a3b8; font-size: 13px; margin-top: 32px;">
                    This link expires in 1 hour. If you didn't request this, you can ignore this email.
                </p>
            </div>
        </div>
    </div>
    """