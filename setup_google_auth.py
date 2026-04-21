"""
Run this ONCE locally to get your Google Calendar OAuth token.

Steps:
  1. Download OAuth credentials from Google Cloud Console and save as google_credentials.json
  2. Run: python setup_google_auth.py
  3. Copy the printed JSON into Railway as the GOOGLE_TOKEN_JSON env var
"""
import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_FILE = "google_credentials.json"


def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"ERROR: {CREDENTIALS_FILE} not found.")
        print("Download it from Google Cloud Console > APIs & Services > Credentials > OAuth 2.0 Client IDs")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    print("\n" + "=" * 60)
    print("Add this as Railway env var  →  GOOGLE_TOKEN_JSON")
    print("=" * 60)
    print(json.dumps(token_data))
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
