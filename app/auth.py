"""Shared-password access with revocable, SQLite-backed browser sessions."""

import hashlib
import json
import secrets
import threading
import time
from collections import deque

from werkzeug.security import check_password_hash, generate_password_hash

from app.database import Database

COOKIE_NAME = "barque_session"
SESSION_SECONDS = 7 * 24 * 3600


class Authentication:
    def __init__(self, database: Database, initial_password: str | None = None):
        if not initial_password:
            raise ValueError("请在 docker-compose.yml 中配置 BARQUE_PASSWORD")
        if not 6 <= len(initial_password) <= 256:
            raise ValueError("BARQUE_PASSWORD 长度须为 6–256 个字符")
        self.database = database
        self.failures = deque(maxlen=10)
        self.lock = threading.Lock()
        with database.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL)"
            )
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT value FROM state WHERE key = 'access'").fetchone()
            current_hash = json.loads(row[0]).get("password_hash") if row else None
            # Compose is authoritative; keep sessions only while its password is unchanged.
            if not current_hash or not check_password_hash(current_hash, initial_password):
                database._write_state(
                    connection,
                    "access",
                    {"password_hash": generate_password_hash(initial_password)},
                )
                connection.execute("DELETE FROM sessions")

    def login(self, password) -> str | None:
        with self.lock:
            now = time.time()
            while self.failures and self.failures[0] < now - 60:
                self.failures.popleft()
            if len(self.failures) >= 10:
                raise PermissionError("尝试次数过多，请一分钟后重试")
            self.failures.append(now)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT value FROM state WHERE key = 'access'").fetchone()
            password_hash = json.loads(row[0])["password_hash"] if row else None
            if (
                not isinstance(password, str)
                or len(password) > 256
                or not password_hash
                or not check_password_hash(password_hash, password)
            ):
                return None
            token = self._create_session(connection)
        with self.lock:
            self.failures.clear()
        return token

    def _create_session(self, connection) -> str:
        token = secrets.token_urlsafe(32)
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?)",
            (self.token_hash(token), time.time() + SESSION_SECONDS),
        )
        return token

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticated(self, token: str | None) -> bool:
        if not token or len(token) > 128:
            return False
        with self.database.connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM sessions WHERE token_hash = ? AND expires_at > ?",
                    (self.token_hash(token), time.time()),
                ).fetchone()
                is not None
            )

    def logout(self, token: str):
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (self.token_hash(token),)
            )
