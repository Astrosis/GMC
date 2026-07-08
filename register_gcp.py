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
    py register_gcp.py <PARENT_ACCOUNT_ID> [developer_email] [flags]

Examples:
    py register_gcp.py 120543441
    py register_gcp.py 120543441 kevin.ngo@abcam.com --key=sa-key.json
    py register_gcp.py 120543441 --sa=admin-api@paid-search-fy26.iam.gserviceaccount.com
    py register_gcp.py 120543441 --no-impersonate

Auth (pick one; registration must run as an identity with Merchant Center admin):
    --key=<path.json>  Run directly AS the service account using its JSON key.
                       Best when the SA — not your email — holds MC admin. The
                       key can request the content scope your user login can't,
                       and needs no impersonation / token-creator.
    --sa=<email>       Impersonate this service account (needs
                       roles/iam.serviceAccountTokenCreator on it).
    (default)          Impersonate GMC_SERVICE_ACCOUNT.
    --no-impersonate   Use your own gcloud login (needs a content-scoped ADC
                       login and your email to have MC admin).

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
DEFAULT_EMAIL = os.environ.get("DEVELOPER_EMAIL", "kevin.ngo@abcam.com")

# NOTE: registerGcp must run as a HUMAN account that holds the Merchant Center
# ADMIN role — the Merchant API rejects service accounts here ("gcp reg is not
# allowed for SA, please use a human account"). So the DEFAULT is your own
# gcloud login. --sa / --key remain only for edge cases / other API calls.
# Empty default => no impersonation => your human login is used.
SERVICE_ACCOUNT = os.environ.get("GMC_SERVICE_ACCOUNT", "")

CONTENT_SCOPE = "https://www.googleapis.com/auth/content"
CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: py register_gcp.py <PARENT_ACCOUNT_ID> [developer_email] [flags]")
        print("  PARENT_ACCOUNT_ID   : your Merchant Center *advanced* account ID")
        print("  --key=<path.json>   : run AS the SA using its JSON key (best if")
        print("                        the SA — not your email — has MC admin)")
        print("  --sa=<email>        : impersonate this service account instead")
        print("  --no-impersonate    : register with your own gcloud login")
        sys.exit(0 if args else 1)

    # ── Flags (order-independent; more reliable than env vars on Windows) ──
    no_impersonate = "--no-impersonate" in args
    args = [a for a in args if a != "--no-impersonate"]

    key_file = None
    service_account = SERVICE_ACCOUNT
    for a in list(args):
        if a.startswith("--key="):
            key_file = a.split("=", 1)[1]
            args.remove(a)
        elif a.startswith("--sa="):
            service_account = a.split("=", 1)[1]
            args.remove(a)

    # A key file authenticates directly AS the SA (no impersonation needed).
    # Otherwise impersonate, unless disabled by flag / env sentinel / empty SA.
    impersonate = (
        not key_file
        and not no_impersonate
        and service_account.strip().lower() not in ("", "none", "-")
    )

    parent_id = args[0].strip().lstrip("accounts/")  # accept bare ID or path
    developer_email = args[1].strip() if len(args) > 1 else DEFAULT_EMAIL

    if key_file:
        auth_desc = f"service-account key {key_file}"
    elif impersonate:
        auth_desc = f"impersonate {service_account}"
    else:
        auth_desc = "your gcloud login (no impersonation)"
    print(f"Registering project '{PROJECT}' with Merchant account {parent_id}")
    print(f"  developer email : {developer_email}")
    print(f"  auth mode       : {auth_desc}\n")

    try:
        if key_file:
            # Authenticate directly as the service account via its JSON key.
            # SA keys honor requested scopes, so we get the content scope your
            # blocked user login can't — and run as the identity that holds
            # Merchant Center admin. No impersonation / token-creator needed.
            from google.oauth2 import service_account as sa_module

            creds = sa_module.Credentials.from_service_account_file(
                key_file, scopes=[CONTENT_SCOPE, CLOUD_SCOPE]
            )
        elif impersonate:
            # Base (your user / ADC) creds, then impersonate the SA with the
            # content scope so the registered GCP project is the SA's project.
            source_creds, _ = google.auth.default(scopes=[CLOUD_SCOPE])
            creds = impersonated_credentials.Credentials(
                source_credentials=source_creds,
                target_principal=service_account,
                target_scopes=[CONTENT_SCOPE],
            )
        else:
            # Use your own login directly; the x-goog-user-project header below
            # tells the API which project to register (must be PROJECT).
            creds, _ = google.auth.default(scopes=[CONTENT_SCOPE, CLOUD_SCOPE])
        session = AuthorizedSession(creds)
    except Exception as e:
        print(f"❌ Auth setup failed: {e}")
        msg = str(e).lower()
        if "gaia id not found" in msg:
            print(
                f"   The service account '{service_account}' does not exist in "
                f"project '{PROJECT}'.\n"
                "   Create it, pass a real one with --sa=<email>, or run with "
                "--no-impersonate to use your own login."
            )
        elif "getaccesstoken" in msg or "permission" in msg:
            print(
                f"   You lack roles/iam.serviceAccountTokenCreator on "
                f"'{service_account}'.\n"
                "   Fix: grant that role, use --key=<path.json> to run as the "
                "SA directly, or --no-impersonate to use your own login."
            )
        else:
            print("   Check `gcloud auth login` / `application-default login`.")
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
                "   403 usually = the acting identity lacks Admin access "
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
