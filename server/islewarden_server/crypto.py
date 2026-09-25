"""Server secrets. Tokens and device keys are stored only as hashes; fingerprint components are peppered.

Hashes are uppercase hex, as the C# server wrote them, so existing devices, leases and bans keep matching.
"""

import base64
import hashlib
import hmac
import secrets
import uuid


class Crypto:
    def __init__(self, pepper: str | None):
        self._pepper = (pepper or "islewarden").encode("utf-8")

    def hash_component(self, kind: str, value: str) -> str:
        """HMAC-SHA256 of a fingerprint component (MAC, MachineGuid...) with the server pepper."""
        return hmac.new(self._pepper, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest().upper()


def new_secret() -> str:
    """32 random bytes as unpadded base64url; also a fresh PKCE verifier."""
    return secrets.token_urlsafe(32)


def new_id() -> str:
    return uuid.uuid4().hex


def hash_token(value: str) -> str:
    """No pepper needed: tokens and device keys are already long and random."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def verify_token(value: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_token(value).encode("utf-8"), expected_hash.encode("utf-8"))


def fixed_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def pkce_challenge(verifier: str) -> str:
    """PKCE S256 (RFC 7636), as the launcher computes it. Non-ASCII becomes "?", like .NET's ASCII encoder."""
    digest = hashlib.sha256(verifier.encode("ascii", errors="replace")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pkce_verify(verifier: str, challenge: str) -> bool:
    return hmac.compare_digest(pkce_challenge(verifier).encode("ascii"), challenge.encode("ascii", errors="replace"))
