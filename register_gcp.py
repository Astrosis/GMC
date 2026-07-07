"""
register_gcp — one-time Merchant API developer registration.
  File "C:\Users\kngo\AppData\Local\Programs\Python\Python313\Lib\site-packages\google\auth\impersonated_credentials.py", line 103, in _make_iam_token_request
    raise exceptions.RefreshError(_REFRESH_ERROR, response_body)
google.auth.exceptions.RefreshError: ('Unable to acquire impersonated credentials', '{\n  "error": {\n    "code": 403,\n    "message": "Permission \'iam.serviceAccounts.getAccessToken\' denied on resource (or it may not exist). Remediate access with this Troubleshooter URL or share it with your administrator - https://console.cloud.google.com/iam-admin/troubleshooter/summary;errorId=CiQwMTlmM2U1OC01N2VhLTc2NjQtYjIyMy1jODNjOGQ2OWIxOWUSAA%3D%3D .",\n    "status": "PERMISSION_DENIED",\n    "details": [\n      {\n        "@type": "type.googleapis.com/google.rpc.ErrorInfo",\n        "reason": "IAM_PERMISSION_DENIED",\n        "domain": "iam.googleapis.com",\n        "metadata": {\n          "permission": "iam.serviceAccounts.getAccessToken",\n          "error_info_id": "CiQwMTlmM2U1OC01N2VhLTc2NjQtYjIyMy1jODNjOGQ2OWIxOWUSAA==",\n          "troubleshooter_url": "https://console.cloud.google.com/iam-admin/troubleshooter/summary;errorId=CiQwMTlmM2U1OC01N2VhLTc2NjQtYjIyMy1jODNjOGQ2OWIxOWUSAA%3D%3D"\n        }\n      }\n    ]\n  }\n}\n')
The Merchant API blocks any call from a GCP project that hasn't been
registered with the Merchant Center account (401 UNAUTHENTICATED,
"...is not registered with the merchant account"). This script performs that
one-time registration in Python, so you don't have to fight Windows shell
quoting with curl.


gcloud iam service-accounts add-iam-policy-binding <SA_EMAIL> --member="user:kevin.ngo@abcam.com" --role="roles/iam.serviceAccountTokenCreator"


Run it ONCE per GCP project, against the PARENT advanced account — that
registration automatically covers every sub-account (.com, .jp, ...).

Usage:
    py register_gcp.py <PARENT_ACCOUNT_ID> [developer_email]

Examples:
    py register_gcp.py 120543441
    py register_gcp.py 120543441 kevin.ngo@abcam.com

Auth:
    Impersonates the service account (gmc-sync@paid-search-fy26...) so the
    project that gets registered is unambiguously the one the SA lives in
    (paid-search-fy26) — regardless of your local gcloud default project.
    Your user account needs roles/iam.serviceAccountTokenCreator on that SA.
    (Run `gcloud auth login` first if you're not already logged in.)

Requires: google-auth, requests (both already pulled in by the pipeline's deps).
"""

import os
import sys
import json

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import AuthorizedSession

# ── Config (env-overridable, matching the pipeline's deployment) ──────────
PROJECT = os.environ.get("BQ_PROJECT", "paid-search-fy26")
SERVICE_ACCOUNT = os.environ.get(
    "GMC_SERVICE_ACCOUNT", "gmc-sync@paid-search-fy26.iam.gserviceaccount.com"
)
DEFAULT_EMAIL = os.environ.get("DEVELOPER_EMAIL", "kevin.ngo@abcam.com")

# Impersonation guarantees the *registered* project is the SA's project. Set
# GMC_SERVICE_ACCOUNT="" (or "none"/"-") to skip it and register using your own
# gcloud login instead — handy if the SA doesn't exist yet. In that case run
# once first:  gcloud auth application-default login --scopes=openid,\
#   https://www.googleapis.com/auth/content,\
#   https://www.googleapis.com/auth/cloud-platform
IMPERSONATE = SERVICE_ACCOUNT.strip().lower() not in ("", "none", "-")

CONTENT_SCOPE = "https://www.googleapis.com/auth/content"
CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: py register_gcp.py <PARENT_ACCOUNT_ID> [developer_email]")
        print("  PARENT_ACCOUNT_ID: your Merchant Center *advanced* account ID")
        sys.exit(0 if len(sys.argv) > 1 else 1)

    parent_id = sys.argv[1].strip().lstrip("accounts/")  # accept bare ID or path
    developer_email = sys.argv[2].strip() if len(sys.argv) > 2 else DEFAULT_EMAIL

    print(f"Registering project '{PROJECT}' with Merchant account {parent_id}")
    print(f"  developer email : {developer_email}")
    print(f"  auth mode       : "
          f"{'impersonate ' + SERVICE_ACCOUNT if IMPERSONATE else 'your gcloud login (no impersonation)'}\n")

    try:
        if IMPERSONATE:
            # Base (your user / ADC) creds, then impersonate the SA with the
            # content scope so the registered GCP project is the SA's project.
            source_creds, _ = google.auth.default(scopes=[CLOUD_SCOPE])
            creds = impersonated_credentials.Credentials(
                source_credentials=source_creds,
                target_principal=SERVICE_ACCOUNT,
                target_scopes=[CONTENT_SCOPE],
            )
        else:
            # Use your own login directly; the x-goog-user-project header below
            # tells the API which project to register (must be PROJECT).
            creds, _ = google.auth.default(scopes=[CONTENT_SCOPE, CLOUD_SCOPE])
        session = AuthorizedSession(creds)
    except Exception as e:
        print(f"❌ Auth setup failed: {e}")
        if "gaia id not found" in str(e).lower():
            print(
                f"   The service account '{SERVICE_ACCOUNT}' does not exist in "
                f"project '{PROJECT}'.\n"
                "   Create it (gcloud iam service-accounts create gmc-sync ...) "
                "OR skip impersonation by setting GMC_SERVICE_ACCOUNT= (empty)."
            )
        else:
            print(
                "   Check: `gcloud auth login` done, and you hold "
                "roles/iam.serviceAccountTokenCreator on the service account."
            )
        sys.exit(1)

    url = (
        "https://merchantapi.googleapis.com/accounts/v1/"
        f"accounts/{parent_id}/developerRegistration:registerGcp"
    )
    resp = session.post(
        url,
        headers={
            "x-goog-user-project": PROJECT,
            "Content-Type": "application/json",
        },
        data=json.dumps({"developerEmail": developer_email}),
    )

    print(f"HTTP {resp.status_code}")
    print(resp.text)

    if resp.status_code == 200:
        print(
            f"\n✅ Done. Project '{PROJECT}' is registered with account "
            f"{parent_id} and all its sub-accounts. Re-run the pipeline."
        )
    else:
        print("\n❌ Registration failed — see the response above.")
        if resp.status_code == 403:
            print(
                "   403 usually = the impersonated identity lacks Admin access "
                "on the Merchant account, or missing token-creator role."
            )
        elif resp.status_code == 409:
            print(
                "   409 usually = this project is already registered to a "
                "DIFFERENT merchant account (one project ↔ one account)."
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
