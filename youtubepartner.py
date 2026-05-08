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

def upload_video(youtube, video_file, data):
    body = {
        'snippet': data['snippet'],
        'status': {
            'privacyStatus': 'private'
        }
    }
    
    # Create a MediaFileUpload object for the video file
    media = MediaFileUpload(video_file, chunksize=-1, resumable=True, mimetype='video/*')

    # Upload the video
    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
    
    return response['id']

def create_asset_and_reference(partner, video_id):
    print("Creating asset and linking reference...")
    asset = partner.assets().insert(
        body={
            'metadata': {
                'title': 'Reference Asset',
                'description': 'Used for Content ID Reference'
            },
            'type': 'web',
            'ownership': {
                'general': {
                    'owner': PARTNER_ID,
                    'ratio': 100,
                    'territories': ['WW']
                }
            }
        },
    ).execute()
    asset_id = asset['id']
    print(f"Created asset ID: {asset_id}")

    partner.references().insert(
        onBehalfOfContentOwner=CONTENT_OWNER_ID,
        body={
            'assetId': asset_id,
            'contentType': 'video',
            'videoId': video_id
        },
    ).execute()
    print("Reference uploaded and linked successfully.")


def get_videos_from_playlist(playlist_id):
    videos = []
    next_page_token = None

    while True:
        request = youtube.playlistItems().list(
            part='contentDetails,id,snippet,status',
            playlistId=playlist_id,
            maxResults=10,  # Number of results per page
            pageToken=next_page_token
        )
        response = request.execute()

        # Add video details to the list
        for item in response['items']:
            videos.append(item)

        # Check if there are more pages of results
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return videos

def get_uploads_playlist_id(channel_id):
    request = youtube.channels().list(
        part='contentDetails',
        id=channel_id
    )
    response = request.execute()

    # Extract uploads playlist ID
    uploads_playlist_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    return uploads_playlist_id

def is_live_video(video):
    thumbnails = video.get('snippet', {}).get('thumbnails', {})
    for thumb in thumbnails.values():
        if '_live.jpg' in thumb.get('url', ''):
            return True
    return False

def download_video(video_id, title):
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"Downloading {title} from {url}...")

        # Set up yt-dlp options
        ydl_opts = {
            'outtmpl': f'{title}.mp4',  # Output filename
            'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',           # Best video quality
            'merge_output_format': 'mp4'
        }

        # Use yt-dlp to download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        print(f"Downloaded: {title}")
    except Exception as e:
        print(f"Failed to download {title}: {e}")

def upload_youtube(videos, youtube, partner):
   
    try:
        for video in videos[0:NO_OF_VIDEO_TO_BE_PROCESS]:
            if not is_live_video(video):
                title = video['snippet']['title']
                download_video(video['snippet']['resourceId']['videoId'], title)
                video_id = upload_video(youtube,f'{title}.mp4',video)
                create_asset_and_reference(partner, video_id)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # if not os.path.exists(DOWNLOADED_FILE):
    #     download_video(VIDEO_URL, DOWNLOADED_FILE)

    # video_id = upload_video(youtube, DOWNLOADED_FILE)
    # create_asset_and_reference(partner, video_id)

    youtube, partner = get_authenticated_services()
    # uploads_playlist_id = get_uploads_playlist_id("UCv71ihaM5rPJtU0npZ5vXMQ")
    # videos = get_videos_from_playlist(uploads_playlist_id)
    # print(f"Uploads Playlist ID: {videos}")

    # upload_youtube(videos=videos, youtube=youtube, partner=partner)


    response = partner.contentOwners().list(fetchMine=True).execute()
    for item in response['items']:
        print(f"Content Owner ID: {item['id']}, {item}")

    
