import resend
import os

# 🔑 Set your API key (make sure it's in .env or replace manually)
resend.api_key = "re_WWWeDpJP_Hk4av2kyw7iAjHGiwyEXHUzY"

def test_resend_email():
    if not resend.api_key:
        print("❌ ERROR: RESEND_API_KEY not set")
        return

    try:
        response = resend.Emails.send({
            "from": "TravelBNB <onboarding@resend.dev>",  # use your verified domain later
            "to": ["hitushaar@gmail.com"],  # 👈 change this to your email
            "subject": "🚀 Resend Test Email",
            "html": """
                <h2>Resend is Working ✅</h2>
                <p>If you received this, your email setup is correct.</p>
            """
        })

        print("✅ Email sent successfully!")
        print("Response:", response)

    except Exception as e:
        print("❌ Failed to send email")
        print("Error:", str(e))


if __name__ == "__main__":
    test_resend_email()