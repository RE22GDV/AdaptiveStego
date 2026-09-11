"""Exception types raised by adaptivestego."""


class StegoError(Exception):
    """Base class for every error raised by this library."""


class CapacityError(StegoError):
    """The message does not fit into the cover image."""


class ContainerError(StegoError):
    """The container is corrupted or was not recognised."""


class CryptoError(StegoError):
    """Encryption or decryption failed (wrong password, tampered data)."""


class PasswordRequired(CryptoError):
    """A container was found but cannot be opened without a password.

    Raised instead of a generic failure so that a caller can do the useful
    thing - ask for the password - rather than report that extraction failed.
    ``certain`` separates a container that says it is encrypted from one that
    only looks like it: a container packed without stored key material carries
    no flag, so the most that can be said about it is that its payload does
    not read as a message and has the entropy of ciphertext.
    """

    def __init__(self, message: str, *, certain: bool = True):
        super().__init__(message)
        self.certain = certain


class DependencyError(StegoError):
    """An optional dependency is required for the requested feature."""
