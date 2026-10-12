"""One-time local OAuth bootstrap. Store the resulting token JSON in GitHub Secrets."""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_FILE = Path("client_secret.json")
TOKEN_FILE = Path("token.json")

if not CLIENT_FILE.exists():
    raise SystemExit("Download an OAuth Desktop App client JSON from Google Cloud and save it as client_secret.json")
flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
print(f"Saved {TOKEN_FILE}. Add its full contents to GitHub Actions secret YOUTUBE_TOKEN_JSON; never commit it.")
