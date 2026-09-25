"""Password hashing shared by the app and make_password_hash.py."""

import hashlib
import hmac
import re
import secrets

ITERATIONS = 600_000
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
MIN_PASSWORD_LENGTH = 8


def make_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored_hash):
    """Check a password against 'pbkdf2_sha256$iterations$salt$hash'."""
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False
