import os
import requests
import yt_dlp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, build_from_document
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NO_OF_VIDEO_TO_BE_PROCESS = 3
_tok = os.environ.get("YOUTUBE_TOKEN_FILE", "").strip()
if _tok:
    TOKEN_FILE = _tok if os.path.isabs(_tok) else os.path.join(_SCRIPT_DIR, _tok)
elif os.path.isfile(os.path.join(_SCRIPT_DIR, "token_for_upload_reference.json")):
    TOKEN_FILE = os.path.join(_SCRIPT_DIR, "token_for_upload_reference.json")
else:
    TOKEN_FILE = os.path.join(_SCRIPT_DIR, "token.json")
# -------- CONFIG --------
CLIENT_SECRET_FILE = os.path.join(_SCRIPT_DIR, "client_secret.json")
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtubepartner'
]
PARTNER_ID = '02huK19J4tiZapOAQkot0g'
CONTENT_OWNER_ID = '02huK19J4tiZapOAQkot0g' 
# ------------------------
def get_partner_api(creds):
    DISCOVERY_URL = "https://www.googleapis.com/discovery/v1/apis/youtubePartner/v1/rest"
    discovery_doc = requests.get(DISCOVERY_URL).json()
    return build_from_document(discovery_doc, credentials=creds)

def get_authenticated_services():
    creds = None

    if os.path.exists(TOKEN_FILE):
        print("Loading credentials from token file...")
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired credentials...")
            try:
                creds.refresh(Request())
            except RefreshError as e:
                print(
                    "Refresh failed (token revoked or invalid). Starting new sign-in.",
                    e,
                )
                creds = None

        if not creds or not creds.valid:
            print("Running OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=8080, prompt='consent')
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

    youtube = build('youtube', 'v3', credentials=creds)
    partner = get_partner_api(creds)
    return youtube, partner


def create_asset_and_reference(partner, video_id):
    print("Creating asset and linking reference...")
    # request = partner.packages().insert(
    #     contentOwner=CONTENT_OWNER_ID,
    #     body={}
    # )

    # # for asset in assets['items']:
    #     print(f"Asset ID: {asset['id']}, Title: {asset['metadata']['title']}")
    asset = partner.assets().insert(
        onBehalfOfContentOwner=CONTENT_OWNER_ID,
        body={
            'metadata': {
                'title': 'Reference Asset'
            },
            'type': 'web'
        }
    ).execute()
    asset_id = asset['id']
    # print(f"Created asset ID: {asset_id}")

    partner.claims().insert(
        onBehalfOfContentOwner=CONTENT_OWNER_ID,
        body={
            "assetId": asset_id,
            "videoId": video_id,
        },
    ).execute()

    # partner.references().insert(
    #     body={
    #         'assetId': asset_id,
    #         'contentType': 'video',
    #         'videoId': video_id
    #     }
    # ).execute()
    # print("Reference uploaded and linked successfully.")

if __name__ == "__main__":


    youtube, partner = get_authenticated_services()


    response = partner.contentOwners().list(fetchMine=True).execute()
    asset = partner.assets().get(assetId="A808023712350041").execute()
    print(asset)


    # for item in response['items']:
    #     print(f"Content Owner ID: {item['id']}, {item}")
    create_asset_and_reference(partner, "yYggbltysyw")