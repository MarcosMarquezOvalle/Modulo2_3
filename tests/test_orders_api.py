from __future__ import annotations

from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from modulo2_3.app import create_app
# create app with in-memory sqlite for tests

app = create_app("sqlite:///:memory:")
client = TestClient(app)


def login_token():
    # ensure the user exists (registration is open for tests)
    client.post("/users", json={"username": "admin", "password": "secret"})
    response = client.post("/login", json={"username": "admin", "password": "secret"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_login_returns_access_token():
    token = login_token()
    assert token


def test_get_orders_requires_authentication():
    response = client.get("/orders")
    assert response.status_code == 401


@given(
    customer_name=st.text(min_size=2, max_size=40)
    .map(lambda v: v.strip())
    .filter(lambda v: v != "" and len(v) >= 2),
    item=st.text(min_size=2, max_size=40)
    .map(lambda v: v.strip())
    .filter(lambda v: v != "" and len(v) >= 2),
    quantity=st.integers(min_value=1, max_value=50),
    unit_price=st.decimals(
        min_value=1,
        max_value=5000,
        allow_nan=False,
        allow_infinity=False,
    ),
    status=st.sampled_from(["pending", "paid", "shipped", "cancelled"]),
)
def test_create_order_accepts_valid_payloads(
    customer_name,
    item,
    quantity,
    unit_price,
    status,
):
    token = login_token()
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "customer_name": customer_name,
        "item": item,
        "quantity": quantity,
        "unit_price": float(unit_price),
        "status": status,
    }

    response = client.post("/orders", json=payload, headers=headers)
    assert response.status_code == 201
    body = response.json()
    assert body["customer_name"] == customer_name
    assert body["item"] == item
    assert body["quantity"] == quantity
    assert body["unit_price"] == float(unit_price)
    assert body["total_amount"] == float(unit_price) * quantity
    assert body["status"] == status


def test_update_order_changes_existing_record():
    token = login_token()
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/orders",
        json={
            "customer_name": "Maria",
            "item": "Monitor",
            "quantity": 1,
            "unit_price": 300.00,
            "status": "pending",
        },
        headers=headers,
    )
    assert create_response.status_code == 201
    order_id = create_response.json()["id"]

    response = client.put(
        f"/orders/{order_id}",
        json={"quantity": 3, "unit_price": 350.25, "status": "paid"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["quantity"] == 3
    assert body["unit_price"] == 350.25
    assert body["status"] == "paid"
    assert body["total_amount"] == 1050.75


def test_delete_order_removes_record():
    token = login_token()
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/orders",
        json={
            "customer_name": "Thomas",
            "item": "Keyboard",
            "quantity": 2,
            "unit_price": 50.00,
        },
        headers=headers,
    )
    assert create_response.status_code == 201
    order_id = create_response.json()["id"]

    response = client.delete(f"/orders/{order_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["detail"] == "Order deleted"

    fetch_response = client.get(f"/orders/{order_id}", headers=headers)
    assert fetch_response.status_code == 404
