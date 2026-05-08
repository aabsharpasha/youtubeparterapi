# CMS Upload / Claim Script

## Setup
- Activate env: `source /Users/aabsharpasha/Desktop/projects/attendance-backend/venv/bin/activate`
- Install deps (if missing): `pip install google-auth google-auth-oauthlib google-api-python-client requests`
- Keep these files in project root:
  - `client_secret.json`
  - `token_for_upload_reference.json` (auto-created after OAuth)

## Run `youtubeclaim.py` with flags
- Full flow (policy + claim + reference):  
  `FLOW_MODE=full python youtubeclaim.py`
- Reference-only check:  
  `FLOW_MODE=reference python youtubeclaim.py`

## What full flow does
- Finds content owner
- Resolves policy from `CLAIM_POLICY_NAME`
- If claim exists: re-applies claim policy + asset match policy
- If no claim: creates asset, sets asset match policy, sets ownership, creates claim, tries reference

## Quick output check
Look for:
- `Applied claim policy: <name> (<policy_id>)`
- `Your match policy`
- `<name> (<policy_id>)`

If both policy IDs match, claim + asset match policy are aligned in portal.
