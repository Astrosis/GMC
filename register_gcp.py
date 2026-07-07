"""
register_gcp — one-time Merchant API developer registration.

The Merchant API blocks any call from a GCP project that hasn't been
registered with the Merchant Center account (401 UNAUTHENTICATED,
"...is not registered with the merchant account"). This script performs that
one-time registration in Python, so you don't have to fight Windows shell
quoting with curl.

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
    print(f"  impersonating   : {SERVICE_ACCOUNT}\n")

    # Base (your user / ADC) credentials, then impersonate the SA with the
    # content scope so the *registered* GCP project is the SA's project.
    try:
        source_creds, _ = google.auth.default(scopes=[CLOUD_SCOPE])
        target_creds = impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=SERVICE_ACCOUNT,
            target_scopes=[CONTENT_SCOPE],
        )
        session = AuthorizedSession(target_creds)
    except Exception as e:
        print(f"❌ Auth setup failed: {e}")
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
