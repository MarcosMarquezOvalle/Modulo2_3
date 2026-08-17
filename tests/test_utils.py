import os
import jwt

from modulo2_3.app import (
    _make_password_hash,
    _verify_password,
    create_token,
    ensure_default_admin,
    authenticate_user_db,
    SECRET_KEY,
    ALGORITHM,
)


def test_password_hash_and_verify():
    hashed = _make_password_hash("s3cr3t", salt="testsalt")
    assert hashed.startswith("testsalt$")
    assert _verify_password("s3cr3t", hashed)
    assert not _verify_password("wrong", hashed)


def test_create_token_and_decode():
    token = create_token("alice")
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == "alice"


def test_ensure_default_admin_and_auth(session, monkeypatch):
    # use known env values to make assertions deterministic
    monkeypatch.setenv("ORDERS_ADMIN_USER", "admin_test")
    monkeypatch.setenv("ORDERS_ADMIN_PASSWORD", "pw_test")
    user = ensure_default_admin(session)
    assert user.username == "admin_test"
    assert authenticate_user_db("admin_test", "pw_test", session)
