from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02, b64urlencode


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_KEY = ROOT / "backend" / "instance" / "vapid-private.pem"


def main():
    PRIVATE_KEY.parent.mkdir(parents=True, exist_ok=True)
    if PRIVATE_KEY.exists():
        vapid = Vapid02.from_file(str(PRIVATE_KEY))
        action = "Reused"
    else:
        vapid = Vapid02()
        vapid.generate_keys()
        vapid.save_key(str(PRIVATE_KEY))
        action = "Created"
    public_bytes = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    private_bytes = vapid.private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    print(f"{action} private key: {PRIVATE_KEY}")
    print("Copy these values into backend\\.env:")
    print("PUSH_ENABLED=true")
    print(f"VAPID_PUBLIC_KEY={b64urlencode(public_bytes)}")
    print(f"VAPID_PRIVATE_KEY={b64urlencode(private_bytes)}")
    print("VAPID_SUBJECT=mailto:your-email@example.com")


if __name__ == "__main__":
    main()
