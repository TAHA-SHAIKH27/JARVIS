"""
google_oauth.py
----------------
Adds Google OAuth 2.0 (installed-app / desktop flow) support so J.A.R.V.I.S.
can call the Gemini API using a linked Google account instead of a raw
API key.

SETUP (one-time, done by the user - not by Jarvis):
1. Go to https://console.cloud.google.com/ -> create/select a project.
2. Enable the "Generative Language API".
3. Configure the OAuth consent screen (External is fine for personal use;
   add yourself as a test user).
4. Create OAuth credentials -> Application type: "Desktop app".
5. Download the resulting JSON and save it next to this file as
   'client_secret.json'.

After that, calling start_oauth_flow() opens a browser window, the user
signs in / consents once, and the resulting token is cached in
'token.json' (auto-refreshed afterwards). No API key is needed while a
valid OAuth session exists.
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Scope required to call generateContent via OAuth (per Google's official
# OAuth quickstart for the Gemini API).
SCOPES = ["https://www.googleapis.com/auth/generative-language.retriever"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")


def is_authenticated() -> bool:
    """Quick check: is there a usable (or refreshable) token on disk?"""
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except Exception:
        return False
    if creds and (creds.valid or (creds.expired and creds.refresh_token)):
        return True
    return False


def start_oauth_flow() -> dict:
    """
    Run the installed-app OAuth consent flow. This opens a local browser
    tab/window for the user to sign in and grant access, then saves the
    resulting credentials to token.json.
    """
    if not os.path.exists(CLIENT_SECRET_FILE):
        return {
            "status": "error",
            "message": (
                "client_secret.json not found next to google_oauth.py. "
                "Download an OAuth 'Desktop app' client from the Google "
                "Cloud Console and save it there first, sir."
            ),
        }

    try:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return {"status": "success", "message": "Google account linked successfully, sir."}
    except Exception as e:
        return {"status": "error", "message": f"OAuth flow failed: {str(e)}"}


def get_credentials():
    """Return valid Credentials (refreshing if needed), or None."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except Exception:
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except Exception:
            return None

    if creds and creds.valid:
        return creds
    return None


def get_access_token() -> str:
    """Return a fresh OAuth access token string, or '' if unavailable."""
    creds = get_credentials()
    return creds.token if creds else ""


def logout() -> dict:
    """Remove the cached token, forcing re-authentication next time."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    return {"status": "success", "message": "Google account unlinked, sir."}
