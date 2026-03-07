import os
import requests
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"


def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    """
    Translate text using the Sarvam AI Translate API.
    Pass source_lang="auto" to enable automatic language detection.

    Language codes (Sarvam format):
        auto   -> auto-detect
        hi-IN  -> Hindi
        en-IN  -> English (India)
        ta-IN  -> Tamil
        te-IN  -> Telugu
        kn-IN  -> Kannada
        ml-IN  -> Malayalam
        mr-IN  -> Marathi
        bn-IN  -> Bengali
        gu-IN  -> Gujarati
        pa-IN  -> Punjabi
        od-IN  -> Odia

    Returns translated text, or original text on any error.
    """
    if not SARVAM_API_KEY:
        print("WARNING: SARVAM_API_KEY not set - returning original text")
        return text

    # Skip only when explicit (non-auto) source matches target
    if source_lang != "auto" and source_lang == target_lang:
        return text

    try:
        payload = {
            "input": text,
            "source_language_code": source_lang,   # "auto" is supported by Sarvam
            "target_language_code": target_lang,
            "speaker_gender": "Male",
            "mode": "formal",
            "model": "mayura:v1",
            "enable_preprocessing": False,
        }

        headers = {
            "Content-Type": "application/json",
            "api-subscription-key": SARVAM_API_KEY,
        }

        response = requests.post(
            SARVAM_TRANSLATE_URL,
            json=payload,
            headers=headers,
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            translated = data.get("translated_text", text)
            print(f"Sarvam translated: '{text}' -> '{translated}'")
            return translated
        else:
            print(f"Sarvam API error {response.status_code}: {response.text}")
            return text

    except Exception as e:
        print(f"Sarvam translation failed: {e}")
        return text
