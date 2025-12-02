import time
import requests
import json
import os

AMIS_CLIENT_ID = os.environ.get("AMIS_CLIENT_ID")
AMIS_CLIENT_SECRET = os.environ.get("AMIS_CLIENT_SECRET")
AMIS_REFRESH_TOKEN = os.environ.get("AMIS_REFRESH_TOKEN")

ZALO_ACCESS_TOKEN = os.environ.get("ZALO_ACCESS_TOKEN")
ZALO_TEMPLATE_ID = os.environ.get("ZALO_TEMPLATE_ID")

STATE_FILE = "state.json"


# ------------------------------------------------------
# Load trạng thái cũ từ file
# ------------------------------------------------------
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ------------------------------------------------------
# Lấy access token mới từ refresh token
# ------------------------------------------------------
def refresh_access_token():
    url = "https://crmconnect.misa.vn/api/v2/account/refreshtoken"

    payload = {
        "client_id": AMIS_CLIENT_ID,
        "client_secret": AMIS_CLIENT_SECRET,
        "refresh_token": AMIS_REFRESH_TOKEN
    }

    headers = {"Content-Type": "application/json"}

    res = requests.post(url, json=payload, headers=headers)
    data = res.json()

    return data["data"]["access_token"]


# ------------------------------------------------------
# Lấy danh sách đơn hàng từ AMIS CRM (SaleOrders)
# ------------------------------------------------------
def get_orders(access_token):
    url = "https://crmconnect.misa.vn/api/v2/SaleOrders"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    res = requests.get(url, headers=headers)
    data = res.json()

    try:
        return data["data"]["SaleOrders"]
    except:
        return []


# ------------------------------------------------------
# Gửi ZNS qua API Render của bạn
# ------------------------------------------------------
def send_zns(order):
    url = "https://your-render-domain.onrender.com/send"

    payload = {
        "phone": order.get("phone"),
        "account_name": order.get("account_name"),
        "sale_order_no": order.get("sale_order_no"),
        "shipping_address": order.get("shipping_address"),
        "sale_order_amount": str(order.get("sale_order_amount"))
    }

    headers = {"Content-Type": "application/json"}

    try:
        requests.post(url, json=payload, headers=headers)
        print("Đã gửi ZNS:", order["sale_order_no"])
    except Exception as e:
        print("Lỗi gửi ZNS:", e)


# ------------------------------------------------------
# Worker Polling Loop
# ------------------------------------------------------
def run_polling():
    state = load_state()

    while True:
        print("Đang cập nhật…")

        # 1. Lấy access token mới
        access_token = refresh_access_token()

        # 2. Lấy danh sách đơn hàng
        orders = get_orders(access_token)

        # 3. So sánh trạng thái giao hàng
        for order in orders:

            oid = order["sale_order_no"]  # Sử dụng số đơn hàng làm ID
            current_status = order.get("delivery_status", "")

            old_status = state.get(oid, "")

            if old_status != current_status:
                print(f"Đơn {oid} đổi trạng thái: {old_status} → {current_status}")

                # Nếu chuyển từ Chưa giao hàng → Đang giao hàng
                if old_status == "Chưa giao hàng" and current_status == "Đang giao hàng":
                    send_zns(order)

                # Lưu trạng thái mới
                state[oid] = current_status

        save_state(state)

        time.sleep(300)   # 5 phút


if __name__ == "__main__":
    run_polling()
