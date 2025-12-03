import time
import requests
import json
import os
import sys
from datetime import datetime

# --- ENV ---
AMIS_CLIENT_ID = os.environ.get("AMIS_CLIENT_ID")
AMIS_CLIENT_SECRET = os.environ.get("AMIS_CLIENT_SECRET")
AMIS_REFRESH_TOKEN = os.environ.get("AMIS_REFRESH_TOKEN")

ZALO_ACCESS_TOKEN = os.environ.get("ZALO_ACCESS_TOKEN")
ZALO_TEMPLATE_ID = os.environ.get("ZALO_TEMPLATE_ID")

RENDER_ZNS_URL = os.environ.get("RENDER_ZNS_URL", "https://amis-zns-polling.onrender.com/send")

STATE_FILE = "state.json"
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))  # default 300s

# Simple helper for timestamped prints
def log(*args, **kwargs):
    print(f"[{datetime.now().isoformat()}]", *args, **kwargs)
    sys.stdout.flush()

# ------------------------------------------------------
# Load / Save state
# ------------------------------------------------------
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        log("Error loading state file:", e)
        return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("Error saving state file:", e)

# ------------------------------------------------------
# Lấy access token mới từ refresh token (robust)
# ------------------------------------------------------
def refresh_access_token(retries=3):
    url = "https://crmconnect.misa.vn/api/v2/account/"
    payload = {
        "client_id": AMIS_CLIENT_ID,
        "client_secret": AMIS_CLIENT_SECRET,
        "refresh_token": AMIS_REFRESH_TOKEN
    }
    headers = {"Content-Type": "application/json"}

    for attempt in range(1, retries + 1):
        try:
            log("Requesting refreshed access token, attempt", attempt)
            res = requests.post(url, json=payload, headers=headers, timeout=15)
        except Exception as e:
            log("Network error when requesting token:", e)
            if attempt < retries:
                time.sleep(2 * attempt)
                continue
            raise

        log("Token endpoint status:", res.status_code)
        text = res.text or ""
        log("Token endpoint response body (truncated):", text[:1000])

        # Try parse JSON safely
        try:
            j = res.json()
        except ValueError:
            # Not JSON — return None or raise with context
            log("Token endpoint did not return JSON. Aborting token refresh.")
            raise RuntimeError(f"Token endpoint returned non-JSON: HTTP {res.status_code}: {text[:1000]}")

        # Try extract token from common shapes:
        # shape1: { "data": { "access_token": "...", "refresh_token":"..." } , "success": true }
        # shape2: { "access_token": "...", "refresh_token":"..." }
        if isinstance(j, dict):
            if "data" in j and isinstance(j["data"], dict) and "access_token" in j["data"]:
                return j["data"]["access_token"]
            if "access_token" in j:
                return j["access_token"]
            # some error wrapper:
            log("Token endpoint JSON but no access_token key. JSON keys:", list(j.keys()))
            raise RuntimeError(f"Token endpoint JSON missing access_token: {j}")

        # default
        raise RuntimeError(f"Unexpected token response format: {j}")

# ------------------------------------------------------
# Lấy danh sách SaleOrders (robust)
# ------------------------------------------------------
def get_saleorders(access_token):
    url = "https://crmconnect.misa.vn/api/v2/SaleOrders"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    try:
        res = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        log("Network error when requesting SaleOrders:", e)
        return None, f"network-error: {e}"

    log("SaleOrders endpoint status:", res.status_code)
    text = res.text or ""
    log("SaleOrders response body (truncated):", text[:1000])

    # If not JSON, return error info
    try:
        j = res.json()
    except ValueError:
        return None, f"non-json-response: HTTP {res.status_code} body: {text[:1000]}"

    # Expecting j["data"]["SaleOrders"] or j["data"]
    if isinstance(j, dict):
        if "data" in j:
            data = j["data"]
            # if data contains SaleOrders
            if isinstance(data, dict) and "SaleOrders" in data:
                return data["SaleOrders"], None
            # if data is a list directly
            if isinstance(data, list):
                return data, None
            # fallback: if j itself contains SaleOrders
        if "SaleOrders" in j:
            return j["SaleOrders"], None

    return None, f"unexpected-json-shape: keys={list(j.keys())}"

# ------------------------------------------------------
# Gửi ZNS tới Render (robust)
# ------------------------------------------------------
def send_zns(order):
    url = RENDER_ZNS_URL
    payload = {
        "phone": order.get("phone"),
        "account_name": order.get("account_name") or order.get("contact_name") or order.get("account_name"),
        "sale_order_no": order.get("sale_order_no"),
        "shipping_address": order.get("shipping_address"),
        "sale_order_amount": str(order.get("sale_order_amount", order.get("sale_order_amount", "")))
    }
    headers = {"Content-Type": "application/json"}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        log("Posted to Render:", r.status_code, r.text[:1000])
        return True
    except Exception as e:
        log("Error posting to Render:", e)
        return False

# ------------------------------------------------------
# Main polling loop
# ------------------------------------------------------
def run_polling():
    if not (AMIS_CLIENT_ID and AMIS_CLIENT_SECRET and AMIS_REFRESH_TOKEN):
        log("Missing AMIS credentials. Please set AMIS_CLIENT_ID/AMIS_CLIENT_SECRET/AMIS_REFRESH_TOKEN env vars.")
        return

    if not (ZALO_ACCESS_TOKEN and ZALO_TEMPLATE_ID):
        log("Warning: ZALO_ACCESS_TOKEN or ZALO_TEMPLATE_ID missing; send_zns will likely fail.")

    state = load_state()

    while True:
        log("=== POLL START ===")
        try:
            access_token = refresh_access_token()
        except Exception as e:
            log("Failed to refresh access token:", e)
            log(f"Sleeping {POLL_INTERVAL}s and retrying...")
            time.sleep(POLL_INTERVAL)
            continue

        orders, err = get_saleorders(access_token)
        if err:
            log("Error getting SaleOrders:", err)
            log(f"Sleeping {POLL_INTERVAL}s and retrying...")
            time.sleep(POLL_INTERVAL)
            continue

        # process orders
        for order in orders:
            # Use sale_order_no as unique key
            oid = order.get("sale_order_no")
            if not oid:
                # skip records without order number
                log("Skipping order without sale_order_no:", order)
                continue

            current_status = order.get("delivery_status", "")
            old_status = state.get(oid)

            # first time see this order -> store and don't send
            if old_status is None:
                state[oid] = current_status
                log(f"Seen first time: {oid} status={current_status} (no ZNS)")
                continue

            if old_status != current_status:
                log(f"Order {oid} changed: {old_status} -> {current_status}")
                # send when Chưa giao hàng -> Đang giao hàng
                if old_status == "Chưa giao hàng" and current_status == "Đang giao hàng":
                    ok = send_zns(order)
                    if ok:
                        log("ZNS sent for", oid)
                    else:
                        log("Failed to send ZNS for", oid)
                # update stored status
                state[oid] = current_status

        save_state(state)
        log("=== POLL END, sleeping", POLL_INTERVAL, "seconds ===")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_polling()

