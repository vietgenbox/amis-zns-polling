import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

AMIS_CLIENT_ID = os.getenv("AMIS_CLIENT_ID")
AMIS_CLIENT_SECRET = os.getenv("AMIS_CLIENT_SECRET")
AMIS_REFRESH_TOKEN = os.getenv("AMIS_REFRESH_TOKEN")

ZALO_ACCESS_TOKEN = os.getenv("ZALO_ACCESS_TOKEN")
ZALO_TEMPLATE_ID = os.getenv("ZALO_TEMPLATE_ID")

STATE_FILE = "sent.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_amis_access_token():
    url = "https://apisv2.misa.vn/auth/token"
    data = {
        "client_id": AMIS_CLIENT_ID,
        "client_secret": AMIS_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": AMIS_REFRESH_TOKEN
    }
    res = requests.post(url, json=data).json()
    return res["access_token"]


def get_orders(access_token):
    url = "https://apisv2.misa.vn/crm/sale-orders"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"page": 1, "page_size": 200}
    res = requests.get(url, headers=headers, params=params).json()
    return res.get("data", [])


def send_zns(phone, account_name, sale_order_no, shipping_address, sale_order_amount):
    url = "https://business.openapi.zalo.me/message/template"
    headers = {
        "access_token": ZALO_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "phone": phone,
        "template_id": ZALO_TEMPLATE_ID,
        "template_data": {
            "account_name": account_name,
            "sale_order_no": sale_order_no,
            "shipping_address": shipping_address,
            "sale_order_amount": sale_order_amount
        }
    }

    res = requests.post(url, headers=headers, json=payload)
    print("ZNS response:", res.text)


def check_and_send():
    state = load_state()
    token = get_amis_access_token()
    orders = get_orders(token)

    for o in orders:
        order_id = o["id"]
        status = o.get("delivery_status")
        phone = o["customer_phone"]
        name = o.get("customer_name", "")
        code = o.get("order_code")

        # Nếu chưa có dữ liệu trước đó
        old_status = state.get(order_id, "")

        # Nếu trạng thái mới là "Đang giao hàng"
        if status == "DangGiaoHang" and old_status != "DangGiaoHang":
    send_zns(
        phone=phone,
        account_name=o.get("customer_name", ""),
        sale_order_no=o.get("order_code"),
        shipping_address=o.get("shipping_address", ""),
        sale_order_amount=o.get("total_amount", "")
    )


        state[order_id] = status

    save_state(state)


if __name__ == "__main__":
    while True:
        print(">>> Kiểm tra trạng thái giao hàng...")
        check_and_send()
        time.sleep(300)  # 5 phút
