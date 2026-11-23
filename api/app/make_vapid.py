"""Generate the key pair that identifies this server to browser push services.

    python -m app.make_vapid

Put the two lines it prints in the server's environment (never commit the private key).
"""

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make() -> tuple[str, str]:
    """(public key as browsers want it, private key as pywebpush wants it)."""
    v = Vapid02()
    v.generate_keys()
    public = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    return b64url(public), b64url(private)


if __name__ == "__main__":
    pub, priv = make()
    print(f"VAPID_PUBLIC_KEY={pub}")
    print(f"VAPID_PRIVATE_KEY={priv}")
    print("PUSH_ENABLED=true")
