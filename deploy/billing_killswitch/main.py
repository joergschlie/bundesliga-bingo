import base64
import json
import os
import urllib.request

PROJECT_ID = os.environ.get("GCP_PROJECT", "")
BILLING_ACCOUNT = os.environ.get("BILLING_ACCOUNT", "")


def get_access_token() -> str:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


def stop_billing(event: dict, context) -> str:
    """
    Triggered by a Cloud Billing Budget Pub/Sub message.
    If costAmount >= budgetAmount (or >= $0.01), detaches the billing account from the project,
    immediately shutting down Cloud Run so zero charges can be incurred.
    """
    raw_data = event.get("data", "")
    if not raw_data:
        return "No data in Pub/Sub message"

    payload = json.loads(base64.b64decode(raw_data).decode("utf-8"))
    cost_amount = float(payload.get("costAmount", 0.0))
    budget_amount = float(payload.get("budgetAmount", 0.0))

    if cost_amount <= 0.0 and cost_amount < budget_amount:
        return f"Within free tier: cost={cost_amount}, budget={budget_amount}"

    token = get_access_token()
    url = f"https://cloudbilling.googleapis.com/v1/projects/{PROJECT_ID}/billingInfo"
    body = json.dumps({"billingAccountName": ""}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = resp.read().decode("utf-8")
    print(f"CRITICAL: Billing disabled for project {PROJECT_ID}. Response: {result}")
    return "Billing disabled and services shut down."
