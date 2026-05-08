import os
import time
import requests
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, build_from_document
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
# CONTENT_OWNER_ID = '02huK19J4tiZapOAQkot0g' 

TOKEN_FILE="token_for_upload_reference.json"
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_tok = os.environ.get("YOUTUBE_TOKEN_FILE", "").strip()
if _tok:
    TOKEN_FILE = _tok if os.path.isabs(_tok) else os.path.join(_SCRIPT_DIR, _tok)
elif os.path.isfile(os.path.join(_SCRIPT_DIR, "token_for_upload_reference.json")):
    TOKEN_FILE = os.path.join(_SCRIPT_DIR, "token_for_upload_reference.json")
else:
    TOKEN_FILE = os.path.join(_SCRIPT_DIR, "token.json")


print(f"TOKEN_FILE: {TOKEN_FILE}")

# -------- CONFIG --------
CLIENT_SECRET_FILE = 'client_secret.json'
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtubepartner'
]

# Claim policy: must match the policy name in YouTube CMS (saved policies).
CLAIM_POLICY_NAME = "Block In All Countries (greater than 2 mins)"
# If the API name differs slightly from CMS, set the id here to skip lookup.
CLAIM_POLICY_ID = None
# Choose flow: "reference" (only references.insert) or "full" (asset+policy+claim+reference).
FLOW_MODE = os.environ.get("FLOW_MODE", "full").strip().lower()
# If True and video already has claim(s), re-apply configured policy to existing claim/asset.
REAPPLY_POLICY_ON_EXISTING = True

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

def print_policy_mapping(policy_id):
    print(f"{CLAIM_POLICY_NAME!r} -> {policy_id}")

def get_policy_map(partner, content_owner_id):
    resp = partner.policies().list(
        onBehalfOfContentOwner=content_owner_id,
        sort="TIME_UPDATED_DESC",
    ).execute()
    return {
        item.get("id"): (item.get("name") or "")
        for item in resp.get("items", [])
        if item.get("id")
    }


def print_applied_policy_details(partner, content_owner_id, claim_id=None, asset_id=None):
    policy_map = get_policy_map(partner, content_owner_id)
    claim_policy_id = None
    asset_policy_id = None

    if claim_id:
        claim = partner.claims().get(
            onBehalfOfContentOwner=content_owner_id,
            claimId=claim_id,
        ).execute()
        claim_policy_id = (claim.get("policy") or {}).get("id")

    if asset_id:
        asset = partner.assets().get(
            onBehalfOfContentOwner=content_owner_id,
            assetId=asset_id,
            fetchMatchPolicy="mine,effective",
        ).execute()
        asset_policy_id = (asset.get("matchPolicyMine") or {}).get("policyId")

    if claim_policy_id:
        print(
            f"Applied claim policy: "
            f"{policy_map.get(claim_policy_id, 'Unknown')} ({claim_policy_id})"
        )
    if asset_policy_id:
        print("Your match policy")
        print(
            f"{policy_map.get(asset_policy_id, 'Unknown')} ({asset_policy_id})"
        )

def set_asset_match_policy(partner, content_owner_id, asset_id, policy_id):
    partner.assetMatchPolicy().patch(
        onBehalfOfContentOwner=content_owner_id,
        assetId=asset_id,
        body={"policyId": policy_id},
    ).execute()

    # Verify policy really changed in CMS "Your match policy".
    asset = partner.assets().get(
        onBehalfOfContentOwner=content_owner_id,
        assetId=asset_id,
        fetchMatchPolicy="mine",
    ).execute()
    applied_policy_id = (asset.get("matchPolicyMine") or {}).get("policyId")
    if applied_policy_id != policy_id:
        raise RuntimeError(
            f"Asset match policy not updated. requested={policy_id}, "
            f"applied={applied_policy_id}"
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


def create_reference_for_existing_claim(partner, content_owner_id, video_id):
    claims = get_existing_claims_for_video(partner, content_owner_id, video_id)
    if not claims:
        raise ValueError(
            f"No existing claims found for video {video_id}. "
            "Reference-only flow requires an existing claim."
        )

    claim = claims[0]
    claim_id = claim.get("id")
    asset_id = claim.get("assetId")
    if not claim_id or not asset_id:
        raise ValueError(
            f"Existing claim missing id/assetId for video {video_id}: {claim}"
        )

    print(f"Reference-only mode: using claim {claim_id}, asset {asset_id}")
    return partner.references().insert(
        onBehalfOfContentOwner=content_owner_id,
        claimId=claim_id,
        body={
            "assetId": asset_id,
            "contentType": "video",
            "videoId": video_id,
        },
    ).execute()

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
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                # The stored refresh token is invalid/revoked; force a new consent flow.
                print(f"Refresh failed ({exc}). Running OAuth flow again...")
                creds = None

        if not creds or not creds.valid:
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
        policy_id = resolve_claim_policy_id(partner, content_owner_id)
        print_policy_mapping(policy_id)
        claim_ids = [c.get("id", "unknown") for c in existing_claims]
        print(
            f"Video {video_id} already has claim(s): {claim_ids}. "
            "Skipping new asset/claim creation."
        )
        if REAPPLY_POLICY_ON_EXISTING:
            existing_claim = existing_claims[0]
            existing_claim_id = existing_claim.get("id")
            existing_asset_id = existing_claim.get("assetId")
            print(
                f"Re-applying policy {policy_id} on existing "
                f"claim={existing_claim_id}, asset={existing_asset_id}"
            )
            if existing_claim_id:
                partner.claims().patch(
                    onBehalfOfContentOwner=content_owner_id,
                    claimId=existing_claim_id,
                    body={"policy": {"id": policy_id}},
                ).execute()
            if existing_asset_id:
                set_asset_match_policy(
                    partner,
                    content_owner_id,
                    existing_asset_id,
                    policy_id,
                )
            print("Re-applied policy on existing claim/asset successfully.")
            print_applied_policy_details(
                partner,
                content_owner_id,
                claim_id=existing_claim_id,
                asset_id=existing_asset_id,
            )
        return existing_claims[0]

    
    policy_id = resolve_claim_policy_id(partner, content_owner_id)
    print_policy_mapping(policy_id)
    print(f"Selected policy for asset+claim: {CLAIM_POLICY_NAME!r} -> {policy_id}")

    # 1. Create the Asset
    asset = partner.assets().insert(
        onBehalfOfContentOwner=content_owner_id,
        body={
            'metadata': {'title': video_title},
            'type': 'web', # Use 'movie' or 'episode' if for TV content
        },
    ).execute()
    asset_id = asset['id']
    print(f"Asset ID created: {asset_id}")
    time.sleep(3)

    # 2. SET OWNERSHIP (required before setting asset match policy)
    # Note: Using 'assetId' instead of 'id'
    owners = [{"owner": content_owner_id, "ratio": 100.0, "type": "exclude", "territories": []}]
    body = {"general": owners}
    partner.ownership().update(
        onBehalfOfContentOwner=content_owner_id,
        assetId=asset_id,
        body=body
    ).execute()
    print("Ownership set successfully.")
    time.sleep(3)

    # 3. Set asset match policy (ownership must already exist)
    set_asset_match_policy(partner, content_owner_id, asset_id, policy_id)
    print("Asset match policy set successfully.")

    # 4. Create the Claim
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
        claim = partner.claims().insert(
            onBehalfOfContentOwner=content_owner_id,
            body=claim_body,
        ).execute()
        claim_id = claim.get("id")

        if claim_id:
            try:
                reference = partner.references().insert(
                    onBehalfOfContentOwner=content_owner_id,
                    claimId=claim_id,
                    body={
                        "assetId": asset_id,
                        "contentType": "video",
                        "videoId": video_id,
                    },
                ).execute()
                print(f"Reference created: {reference.get('id')}")
            except HttpError as exc:
                # Some videos/claims are not eligible for references API linkage.
                print(
                    f"Reference insert skipped for claim {claim_id}, video {video_id}, "
                    f"asset {asset_id}: {exc}"
                )
        print_applied_policy_details(
            partner,
            content_owner_id,
            claim_id=claim_id,
            asset_id=asset_id,
        )
        return claim
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
    video_id = "vdQHRVpdgz0"
    title = get_video_title(youtube, video_id)
    if FLOW_MODE == "reference":
        reference = create_reference_for_existing_claim(
            partner, content_owner_id, video_id
        )
        print(f"Reference result: {reference}")
    else:
        create_asset_and_reference(partner, video_id, content_owner_id, title)