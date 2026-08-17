from fastapi.testclient import TestClient


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_user_and_order_flow(client: TestClient):
    # register user
    r = client.post("/users", json={"username": "alice", "password": "pass"})
    assert r.status_code == 201
    data = r.json()
    assert data["username"] == "alice"

    # login
    r = client.post("/login", json={"username": "alice", "password": "pass"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # create order (include total_amount placeholder; server will overwrite)
    order_payload = {
        "customer_name": "Bob",
        "item": "Widget",
        "quantity": 2,
        "unit_price": 10.0,
        "total_amount": 0,
    }
    r = client.post("/orders", json=order_payload, headers=headers)
    assert r.status_code == 201
    order = r.json()
    assert float(order["total_amount"]) == 20.0
    order_id = order["id"]

    # list orders
    r = client.get("/orders", headers=headers)
    assert r.status_code == 200
    orders = r.json()
    assert any(o["id"] == order_id for o in orders)

    # get order
    r = client.get(f"/orders/{order_id}", headers=headers)
    assert r.status_code == 200

    # update order
    r = client.put(f"/orders/{order_id}", json={"quantity": 3}, headers=headers)
    assert r.status_code == 200
    assert float(r.json()["total_amount"]) == 30.0

    # delete order
    r = client.delete(f"/orders/{order_id}", headers=headers)
    assert r.status_code == 200

    # ensure deleted
    r = client.get(f"/orders/{order_id}", headers=headers)
    assert r.status_code == 404
