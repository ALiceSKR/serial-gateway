import hashlib
import hmac
import os
import secrets
import time

from fastapi import Cookie, HTTPException, status


class SessionManager:
    def __init__(self) -> None:
        self.username = os.getenv("SERIAL_GATEWAY_USERNAME", "admin")
        self.password = os.getenv("SERIAL_GATEWAY_PASSWORD", "admin123")
        self.secret = os.getenv("SERIAL_GATEWAY_SECRET", secrets.token_hex(32)).encode()
        self.ttl = 12 * 60 * 60

    def authenticate(self, username: str, password: str) -> bool:
        return hmac.compare_digest(username, self.username) and hmac.compare_digest(
            password, self.password
        )

    def create(self) -> str:
        expires = str(int(time.time()) + self.ttl)
        nonce = secrets.token_urlsafe(18)
        payload = f"{self.username}.{expires}.{nonce}"
        signature = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def validate(self, token: str | None) -> str:
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
        try:
            username, expires, nonce, signature = token.split(".", 3)
            payload = f"{username}.{expires}.{nonce}"
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
            valid = hmac.compare_digest(signature, expected)
            valid = valid and username == self.username and int(expires) >= int(time.time())
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
        return username


sessions = SessionManager()


def require_user(serial_gateway_session: str | None = Cookie(default=None)) -> str:
    return sessions.validate(serial_gateway_session)
