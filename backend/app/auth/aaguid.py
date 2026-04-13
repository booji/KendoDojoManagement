"""AAGUID → authenticator name lookup.

A small static mapping of well-known AAGUIDs to human-readable authenticator
names. label_from_aaguid is the only public interface.
"""

from __future__ import annotations

_KNOWN: dict[str, str] = {
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Mac",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "dd4ec289-e01d-41c9-bb89-70fa845d4bf2": "iCloud Keychain",
    "2fc0579f-8113-47ea-b116-bb5a8db9202a": "YubiKey 5 NFC",
    # Additional well-known entries
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello PIN",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6e96969e-a5cf-4aad-9b56-305fe6c82795": "Windows Hello",
    "f8a011f3-8c0a-4d15-8006-17111f9edc7d": "Security Key by Yubico",
    "b92c3f9a-c014-4056-887f-140a2501163b": "Security Key by Yubico",
    "ee882879-721c-4913-9775-3dfcce97072a": "YubiKey 5 Series",
    "fa2b99dc-9e39-4257-8f92-4a30d23c4118": "YubiKey 5 NFC FIPS",
    "c1f9a0bc-1dd2-404a-b27f-8e29047a43fd": "YubiKey 5 FIPS Series",
    "73402251-f2a8-4f03-873e-3cb6db604b03": "uTrust FIDO2 Security Key",
    "d8522d9f-575b-4866-88a9-ba99fa02f35b": "YubiKey Bio Series",
    "aaguid-not-set": "Passkey",
}


def label_from_aaguid(aaguid: str | None) -> str:
    """Return a human-readable authenticator name for the given AAGUID.

    Falls back to "Passkey" for unknown or absent AAGUIDs.
    """
    if not aaguid:
        return "Passkey"
    return _KNOWN.get(aaguid, "Passkey")
