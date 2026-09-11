"""Tests for the two ways an encrypted container can carry its key material.

By default the salt, the nonce and the ENCRYPTED flag are written into the
container, which is the textbook arrangement. With ``store_key_material=False``
none of them are, and the container becomes indistinguishable from an
unencrypted one until someone supplies the password.
"""

import zlib

import numpy as np
from conftest import raises, skip

import adaptivestego as sl
from adaptivestego import container, crypto
from adaptivestego.exceptions import CryptoError, PasswordRequired
from adaptivestego.testing import synthetic_cover

MESSAGE = "Съешь ещё этих мягких французских булок, but in UTF-8 ✓"
PASSWORD = "correct horse battery staple"


def _needs_crypto():
    if not crypto.available():
        skip("the cryptography package is not installed")


# ---------------------------------------------------------------------------
# the container itself
# ---------------------------------------------------------------------------
def test_the_password_is_never_in_the_container_in_either_mode():
    """The obvious property, asserted because it is the whole point."""
    _needs_crypto()
    secret = "hunter2-a-very-distinctive-password"
    for store in (True, False):
        blob = container.pack(MESSAGE, password=secret, compress=False,
                              store_key_material=store)
        assert secret.encode("utf-8") not in blob
        assert secret.encode("utf-16-le") not in blob


def test_derived_mode_leaves_no_key_material_in_the_header():
    _needs_crypto()
    stored = container.pack(MESSAGE, password=PASSWORD, compress=False)
    derived = container.pack(MESSAGE, password=PASSWORD, compress=False,
                             store_key_material=False)

    stored_header = container.parse_preamble(stored)
    derived_header = container.parse_preamble(derived)
    assert stored_header.encrypted
    assert not derived_header.encrypted

    # Exactly the salt and the nonce shorter, and nothing else changed.
    assert len(stored) - len(derived) == crypto.SALT_LEN + crypto.NONCE_LEN


def test_a_derived_container_looks_like_an_unencrypted_one():
    """Byte for byte, the header of a derived container is the plain shape.

    Not a claim that the payload is indistinguishable from a plaintext one -
    ciphertext has the entropy of ciphertext - but the header says nothing.
    """
    _needs_crypto()
    plain = container.pack("x" * 64, compress=False)
    derived = container.pack("x" * 64, password=PASSWORD, compress=False,
                             store_key_material=False)
    assert len(derived) == len(plain) + crypto.TAG_LEN
    assert derived[:6] == plain[:6]            # magic, version, flags


def test_derived_mode_round_trips():
    _needs_crypto()
    for compress in (True, False):
        blob = container.pack(MESSAGE, password=PASSWORD, compress=compress,
                              store_key_material=False)
        offset = [0]

        def read(n, _blob=blob, _offset=offset):
            chunk = _blob[_offset[0]:_offset[0] + n]
            _offset[0] += n
            return chunk

        message, header = container.unpack(read, password=PASSWORD)
        assert message.decode("utf-8") == MESSAGE
        assert not header.encrypted


def test_derived_mode_needs_a_password_to_pack():
    exc = raises(ValueError, container.pack, "hello", store_key_material=False)
    assert "no key material" in str(exc)


def test_the_same_message_and_password_give_the_same_container():
    """Derived mode is deterministic, and that is a documented trade.

    Stored mode draws a fresh salt and nonce every time, so two containers of
    the same message differ. Derived mode cannot, and an observer who sees two
    identical containers learns that the two messages were identical.
    """
    _needs_crypto()
    first = container.pack(MESSAGE, password=PASSWORD, store_key_material=False)
    second = container.pack(MESSAGE, password=PASSWORD, store_key_material=False)
    assert first == second

    stored_first = container.pack(MESSAGE, password=PASSWORD)
    stored_second = container.pack(MESSAGE, password=PASSWORD)
    assert stored_first != stored_second


def test_different_messages_get_different_nonces():
    """Nonce reuse under one key breaks GCM, so this is the property to check.

    The derived nonce is a function of the password and of the header fields,
    which is why two different messages must produce two different headers.
    """
    _needs_crypto()
    contexts = set()
    for index in range(64):
        message = f"message number {index}"
        plain = message.encode("utf-8")
        blob = container.pack(message, password=PASSWORD, compress=False,
                              store_key_material=False)
        header = container.parse_preamble(blob)
        context = container._derivation_context(
            header.flags, 0, len(plain) + crypto.TAG_LEN, len(plain),
            zlib.crc32(plain) & 0xFFFFFFFF)
        contexts.add(context)
    assert len(contexts) == 64


# ---------------------------------------------------------------------------
# through the whole pipeline
# ---------------------------------------------------------------------------
def test_embed_and_extract_without_stored_key_material():
    _needs_crypto()
    cover = synthetic_cover(128, 128, seed=11)
    result = sl.embed(cover, MESSAGE, method="adaptive", key="place",
                      password=PASSWORD, store_key_material=False)
    recovered = sl.extract(result.stego, method="adaptive", key="place",
                           password=PASSWORD)
    assert recovered == MESSAGE


def test_a_wrong_password_is_reported_as_a_wrong_password():
    _needs_crypto()
    cover = synthetic_cover(128, 128, seed=12)
    for store in (True, False):
        result = sl.embed(cover, MESSAGE, method="adaptive", key="place",
                          password=PASSWORD, store_key_material=store)
        exc = raises(CryptoError, sl.extract, result.stego, method="adaptive",
                     key="place", password="not the password")
        assert "password" in str(exc).lower()


def test_a_missing_password_asks_for_one_in_both_modes():
    """The point of the two-phase read: a missing password is a question.

    In stored mode the header says so outright. In derived mode there is no
    flag to read, so the answer rests on the payload not being readable and
    being exactly the size of a plaintext plus a GCM tag - and ``certain``
    reports which of the two it was.
    """
    _needs_crypto()
    cover = synthetic_cover(128, 128, seed=13)
    for store, certain in ((True, True), (False, False)):
        result = sl.embed(cover, MESSAGE, method="adaptive", key="place",
                          password=PASSWORD, compress=False,
                          store_key_material=store)
        exc = raises(PasswordRequired, sl.extract, result.stego,
                     method="adaptive", key="place")
        assert exc.certain is certain


def test_a_password_on_a_plaintext_container_is_harmless():
    """Offering a password where none is needed must not break extraction.

    Derived mode makes this a real case: with no flag to consult, extraction
    tries to decrypt first and has to fall back cleanly when that fails.
    """
    cover = synthetic_cover(96, 96, seed=14)
    result = sl.embed(cover, "no password here", method="adaptive", key="place")
    assert sl.extract(result.stego, method="adaptive", key="place",
                      password="irrelevant") == "no password here"


def test_capacity_accounts_for_the_mode():
    """Derived mode saves the salt and the nonce, so more message fits."""
    _needs_crypto()
    cover = synthetic_cover(64, 64, seed=15, channels=1)
    stored = sl.capacity(cover, "adaptive", password=PASSWORD)
    derived = sl.capacity(cover, "adaptive", password=PASSWORD,
                          store_key_material=False)
    difference = crypto.SALT_LEN + crypto.NONCE_LEN
    assert derived["container_overhead_bytes"] == (
        stored["container_overhead_bytes"] - difference)
    assert derived["message_bytes_max"] == (stored["message_bytes_max"]
                                            + difference)


def test_the_reported_capacity_is_exactly_reachable():
    """The largest message that is said to fit must fit, and one more must not."""
    _needs_crypto()
    cover = synthetic_cover(48, 48, seed=16, channels=1)
    for ecc_nsym in (0, 8):
        info = sl.capacity(cover, "adaptive", password=PASSWORD,
                           ecc_nsym=ecc_nsym, store_key_material=False)
        limit = info["message_bytes_max"]
        message = b"\xa5" * limit
        result = sl.embed(cover, message, method="adaptive", password=PASSWORD,
                          ecc_nsym=ecc_nsym, store_key_material=False,
                          compress=False)
        assert sl.extract(result.stego, method="adaptive", password=PASSWORD,
                          as_text=False) == message
        raises(sl.CapacityError, sl.embed, cover, b"\xa5" * (limit + 1),
               method="adaptive", password=PASSWORD, ecc_nsym=ecc_nsym,
               store_key_material=False, compress=False)


def test_error_correction_still_works_without_stored_key_material():
    _needs_crypto()
    if not __import__("adaptivestego.ecc", fromlist=["ecc"]).available():
        skip("the reedsolo package is not installed")
    cover = synthetic_cover(160, 160, seed=17)
    result = sl.embed(cover, MESSAGE, method="adaptive", key="place",
                      password=PASSWORD, ecc_nsym=16, store_key_material=False)
    assert sl.extract(result.stego, method="adaptive", key="place",
                      password=PASSWORD) == MESSAGE


def test_the_derived_context_is_authenticated():
    """Editing the header of a derived container must not decrypt to garbage.

    The context is passed to GCM as associated data, so a receiver that
    reconstructs it from tampered header fields gets an authentication
    failure - which is the difference between a detected forgery and a
    plausible wrong answer.
    """
    _needs_crypto()
    plain = b"twenty-four bytes here!!"
    context = container._derivation_context(0, 0, len(plain) + crypto.TAG_LEN,
                                            len(plain), 12345)
    blob = crypto.encrypt_derived(plain, PASSWORD, context)
    assert crypto.decrypt_derived(blob, PASSWORD, context) == plain

    other = container._derivation_context(0, 0, len(plain) + crypto.TAG_LEN,
                                          len(plain), 12346)
    raises(CryptoError, crypto.decrypt_derived, blob, PASSWORD, other)


def test_derived_key_material_depends_on_the_password():
    _needs_crypto()
    context = b"a fixed context"
    assert crypto.derived_salt("one", context) != crypto.derived_salt("two", context)
    assert crypto.derived_salt("one", context) == crypto.derived_salt("one", context)
    key = crypto.derive_key("one", crypto.derived_salt("one", context))
    assert len(crypto.derived_nonce(key, context)) == crypto.NONCE_LEN
    assert (crypto.derived_nonce(key, b"a")
            != crypto.derived_nonce(key, b"b"))


def test_stego_images_of_the_two_modes_differ():
    """A sanity check that the mode really reaches the image."""
    _needs_crypto()
    cover = synthetic_cover(96, 96, seed=18)
    stored = sl.embed(cover, MESSAGE, method="adaptive", key="k",
                      password=PASSWORD, store_key_material=True).stego
    derived = sl.embed(cover, MESSAGE, method="adaptive", key="k",
                       password=PASSWORD, store_key_material=False).stego
    assert not np.array_equal(stored, derived)
