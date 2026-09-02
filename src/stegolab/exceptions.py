"""Exception types raised by stegolab."""


class StegoError(Exception):
    """Base class for every error raised by this library."""


class CapacityError(StegoError):
    """The message does not fit into the cover image."""


class ContainerError(StegoError):
    """The container is corrupted or was not recognised."""


class CryptoError(StegoError):
    """Encryption or decryption failed (wrong password, tampered data)."""


class DependencyError(StegoError):
    """An optional dependency is required for the requested feature."""
