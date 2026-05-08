import os
import requests
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, build_from_document
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
# CONTENT_OWNER_ID = '02huK19J4tiZapOAQkot0g' 

TOKEN_FILE="cms-upload/token_for_upload_reference.json"
# -------- CONFIG --------
CLIENT_SECRET_FILE = 'youtube-cms/client_secret.json'
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtubepartner'
]

# Claim policy: must match the policy name in YouTube CMS (saved policies).
CLAIM_POLICY_NAME = "Block In All Countries (greater than 2 mins)"
# If the API name differs slightly from CMS, set the id here to skip lookup.
CLAIM_POLICY_ID = None

def get_partner_api(creds):
    DISCOVERY_URL = "https://www.googleapis.com/discovery/v1/apis/youtubePartner/v1/rest"
    discovery_doc = requests.get(DISCOVERY_URL).json()
    return build_from_document(discovery_doc, credentials=creds)


def resolve_claim_policy_id(partner, content_owner_id):
    if CLAIM_POLICY_ID:
        return CLAIM_POLICY_ID
    resp = partner.policies().list(
        onBehalfOfContentOwner=content_owner_id,
        sort="TIME_UPDATED_DESC",
    ).execute()
    target = CLAIM_POLICY_NAME.strip().casefold()
    for item in resp.get("items", []):
        name = (item.get("name") or "").strip()
        if name.casefold() == target:
            return item["id"]
    names = sorted({(item.get("name") or "").strip() for item in resp.get("items", []) if item.get("name")})
    preview = names[:40]
    more = f" (+{len(names) - 40} more)" if len(names) > 40 else ""
    raise ValueError(
        f"Policy {CLAIM_POLICY_NAME!r} not found for this content owner. "
        f"Available names ({len(names)}): {preview}{more}"
    )


def get_video_title(youtube, video_id):
    resp = youtube.videos().list(part='snippet', id=video_id, maxResults=1).execute()
    items = resp.get('items', [])
    if not items:
        raise ValueError(f"No video found for id: {video_id}")
    return items[0]['snippet']['title']


def get_existing_claims_for_video(partner, content_owner_id, video_id):
    resp = partner.claims().list(
        onBehalfOfContentOwner=content_owner_id,
        videoId=video_id,
    ).execute()
    return resp.get("items", [])

def get_authenticated_services():
    creds = None

    if os.path.exists(TOKEN_FILE):
        print("Loading credentials from token file...")
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

            
    if not creds or not creds.valid:
        print("No valid credentials found, initiating OAuth flow...")
        if creds and creds.expired and creds.refresh_token:
            # Refresh the token if it's expired
            print("Refreshing expired credentials...")
            creds.refresh(Request())
        else:
            # Run the OAuth flow to get new credentials
            print("Running OAuth flow...")
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        creds = flow.run_local_server(port=8080, prompt='consent')

        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    youtube = build('youtube', 'v3', credentials=creds)
    partner = get_partner_api(creds)
    return youtube, partner

def create_asset_and_reference(partner, video_id, content_owner_id, video_title):
    existing_claims = get_existing_claims_for_video(partner, content_owner_id, video_id)
    if existing_claims:
        claim_ids = [c.get("id", "unknown") for c in existing_claims]
        print(
            f"Video {video_id} already has claim(s): {claim_ids}. "
            "Skipping new asset/claim creation."
        )
        return existing_claims[0]

    # 1. Create the Asset
    asset = partner.assets().insert(
        onBehalfOfContentOwner=content_owner_id,
        body={
            'metadata': {'title': video_title},
            'type': 'web' # Use 'movie' or 'episode' if for TV content
        },
    ).execute()
    asset_id = asset['id']
    print(f"Asset ID created: {asset_id}")

    # 2. SET OWNERSHIP
    # Note: Using 'assetId' instead of 'id'
    owners = [{"owner": content_owner_id, "ratio": 100.0, "type": "exclude", "territories": []}]
    body = {"general": owners}
    partner.ownership().update(
        onBehalfOfContentOwner=content_owner_id,
        assetId=asset_id,
        body=body
    ).execute()
    print("Ownership set successfully.")

    # 3. Create the Claim
    policy_id = resolve_claim_policy_id(partner, content_owner_id)
    print(f"Claim policy: {CLAIM_POLICY_NAME!r} -> {policy_id}")

    claim_body = {
        "assetId": asset_id,
        "videoId": video_id,
        "contentType": "audiovisual",
        "policy": {
            "id": policy_id
        },
    }

    try:
        return partner.claims().insert(
            onBehalfOfContentOwner=content_owner_id,
            body=claim_body,
        ).execute()
    except HttpError as exc:
        if exc.resp is not None and exc.resp.status == 409:
            existing_claims = get_existing_claims_for_video(partner, content_owner_id, video_id)
            claim_ids = [c.get("id", "unknown") for c in existing_claims]
            print(
                f"Claim insert returned 409 alreadyClaimed for video {video_id}. "
                f"Existing claim(s): {claim_ids}"
            )
            if existing_claims:
                return existing_claims[0]
        raise
   
if __name__ == "__main__":


    youtube, partner = get_authenticated_services()

    response = partner.contentOwners().list(fetchMine=True).execute()
    content_owner_id = None
    for item in response['items']:
        content_owner_id = item['id']
        if content_owner_id:
            break
    if not content_owner_id:
        raise Exception("Content Owner ID not found")
    print(f"Content Owner ID: {content_owner_id}")
    video_id = "sH44axc8Aic"
    title = get_video_title(youtube, video_id)
    create_asset_and_reference(partner, video_id, content_owner_id, title)