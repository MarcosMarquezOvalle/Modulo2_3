from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from enum import Enum as PyEnum
import os

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

SECRET_KEY = os.environ.get("ORDERS_SECRET_KEY", "orders-api-secret-key-32-byte-minimum-abc")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
security = HTTPBearer()


class OrderStatus(str, PyEnum):
    pending = "pending"
    paid = "paid"
    shipped = "shipped"
    cancelled = "cancelled"


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_name: str
    item: str
    quantity: int
    unit_price: float
    total_amount: float
    status: OrderStatus = OrderStatus.pending
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LoginRequest(SQLModel):
    username: str
    password: str


# User model and password utilities (simple PBKDF2-HMAC-SHA256)
import hashlib
import secrets


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _make_password_hash(password: str, *, salt: str | None = None) -> str:
    if password is None:
        password = ""
    if salt is None:
        salt = secrets.token_hex(16)
    pw = password.encode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha256", pw, salt.encode("utf-8"), 100_000)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, hexhash = stored.split("$", 1)
    except Exception:
        return False
    pw = password.encode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha256", pw, salt.encode("utf-8"), 100_000)
    return secrets.compare_digest(dk.hex(), hexhash)


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def authenticate_user_db(username: str, password: str, session: Session) -> bool:
    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        return False
    return _verify_password(password, user.hashed_password)


def ensure_default_admin(session: Session):
    admin_user = os.environ.get("ORDERS_ADMIN_USER", "admin")
    admin_pass = os.environ.get("ORDERS_ADMIN_PASSWORD", "secret")
    existing = session.exec(select(User).where(User.username == admin_user)).first()
    if existing:
        return existing
    user = User(username=admin_user, hashed_password=_make_password_hash(admin_pass))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict[str, str]:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    username = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"username": username}


def get_engine(database_url: Optional[str] = None):
    if database_url is None:
        database_url = os.environ.get("DATABASE_URL", "sqlite:///orders.db")
    connect_args = {}
    engine_kwargs = {}
    if database_url.startswith("sqlite"):
        # when using in-memory SQLite for tests, use StaticPool so the same connection is reused
        connect_args = {"check_same_thread": False}
        if database_url == "sqlite:///:memory:":
            engine_kwargs = {"poolclass": StaticPool}
    engine = create_engine(database_url, echo=False, connect_args=connect_args, **engine_kwargs)
    return engine


def create_app(database_url: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="Orders API", version="1.0.0")

    engine = get_engine(database_url)
    # Ensure tables exist immediately (important for tests using in-memory SQLite)
    SQLModel.metadata.create_all(engine)

    def get_session():
        with Session(engine) as session:
            yield session

    # NOTE: we provide ensure_default_admin(session) helper, but do not auto-create users at import-time
    @app.post("/login")
    def login(payload: LoginRequest, session: Session = Depends(get_session)):
        if not authenticate_user_db(payload.username, payload.password, session):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        token = create_token(payload.username)
        return {"access_token": token, "token_type": "bearer"}

    @app.post("/users", status_code=status.HTTP_201_CREATED)
    def create_user_endpoint(payload: LoginRequest, session: Session = Depends(get_session)):
        # simple registration endpoint
        existing = session.exec(select(User).where(User.username == payload.username)).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
        hashed = _make_password_hash(payload.password)
        user = User(username=payload.username, hashed_password=hashed)
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"id": user.id, "username": user.username}

    @app.get("/orders")
    def list_orders(_: dict[str, str] = Depends(get_current_user), session: Session = Depends(get_session)):
        orders = session.exec(select(Order)).all()
        return orders

    @app.post("/orders", status_code=status.HTTP_201_CREATED)
    def create_order(order: Order, _: dict[str, str] = Depends(get_current_user), session: Session = Depends(get_session)):
        order.total_amount = float(order.quantity * order.unit_price)
        order.created_at = datetime.now(timezone.utc)
        order.updated_at = datetime.now(timezone.utc)
        session.add(order)
        session.commit()
        session.refresh(order)
        return order

    @app.get("/orders/{order_id}")
    def get_order(order_id: int, _: dict[str, str] = Depends(get_current_user), session: Session = Depends(get_session)):
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order

    @app.put("/orders/{order_id}")
    def update_order(order_id: int, payload: dict, _: dict[str, str] = Depends(get_current_user), session: Session = Depends(get_session)):
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        # apply allowed updates
        for key in ("customer_name", "item", "quantity", "unit_price", "status"):
            if key in payload and payload[key] is not None:
                setattr(order, key, payload[key])
        order.total_amount = float(order.quantity * order.unit_price)
        order.updated_at = datetime.now(timezone.utc)
        session.add(order)
        session.commit()
        session.refresh(order)
        return order

    @app.delete("/orders/{order_id}")
    def delete_order(order_id: int, _: dict[str, str] = Depends(get_current_user), session: Session = Depends(get_session)):
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        session.delete(order)
        session.commit()
        return {"detail": "Order deleted"}

    @app.get("/health")
    def health_check():
        return {"status": "ok"}

    # attach engine and models for tests/inspection
    app.state._engine = engine
    app.state._models = (Order,)

    return app

# Note: this module exposes create_app(database_url) to construct the FastAPI app.
# A default app instance is provided so servers can import `modulo2_3.app:app` or
# `modulo2_3.main:app`.
app = create_app()
