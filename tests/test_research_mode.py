"""Tests for research mode, exact capacity accounting and experiment design.

These cover the defects that make experimental results wrong rather than the
program crash, so they are the ones worth keeping honest.
"""

import numpy as np
from conftest import raises, skip

import adaptivestego as sl
from adaptivestego import container, ecc
from adaptivestego.codecs import EmbedParams, get_codec
from adaptivestego.exceptions import CapacityError
from adaptivestego.prng import deterministic_bits, deterministic_bytes
from adaptivestego.testing import synthetic_cover

METHODS = sl.codec_names()


# ---------------------------------------------------------------------------
# exact capacity, including the Reed-Solomon block expansion
# ---------------------------------------------------------------------------
def test_capacity_is_exact_without_ecc():
    img = synthetic_cover(64, 64)
    limit = sl.capacity(img, method="random")["message_bytes_max"]
    sl.embed(img, b"x" * limit, method="random", key="k", compress=False)
    raises(CapacityError, sl.embed, img, b"x" * (limit + 1), method="random",
           key="k", compress=False)


def test_capacity_is_exact_with_ecc():
    """The advertised maximum must fit and one more byte must not.

    Subtracting a constant overhead is wrong here: Reed-Solomon expands the
    payload block by block and pads the last block to 223 bytes, so the true
    limit is a step function of the message length.
    """
    if not ecc.available():
        skip("needs the reedsolo package")
    img = synthetic_cover(64, 64)
    for nsym in (1, 4, 8, 16, 32):
        limit = sl.capacity(img, method="random", ecc_nsym=nsym)["message_bytes_max"]
        sl.embed(img, b"x" * limit, method="random", key="k", compress=False,
                 ecc_nsym=nsym)
        raises(CapacityError, sl.embed, img, b"x" * (limit + 1), method="random",
               key="k", compress=False, ecc_nsym=nsym)


def test_capacity_is_exact_with_encryption():
    from adaptivestego import crypto

    if not crypto.available():
        skip("needs the cryptography package")
    img = synthetic_cover(64, 64)
    limit = sl.capacity(img, method="random", password="pw")["message_bytes_max"]
    sl.embed(img, b"x" * limit, method="random", key="k", password="pw",
             compress=False)
    raises(CapacityError, sl.embed, img, b"x" * (limit + 1), method="random",
           key="k", password="pw", compress=False)


def test_max_message_bytes_is_monotone_and_tight():
    for nsym in (0, 8, 32):
        previous = 0
        for capacity_bytes in range(0, 2000, 37):
            limit = container.max_message_bytes(capacity_bytes, ecc_nsym=nsym)
            assert limit >= previous          # monotone in the capacity
            previous = limit
            if limit:
                assert container.container_size(limit, 0, nsym) <= capacity_bytes
            assert container.container_size(limit + 1, 0, nsym) > capacity_bytes


# ---------------------------------------------------------------------------
# research mode: exactly m bits, no header
# ---------------------------------------------------------------------------
def test_raw_roundtrip_for_every_method():
    img = synthetic_cover(128, 128)
    n_bits = sl.payload_bits_for_bpp(img, 0.3)
    payload = deterministic_bits("key", "payload", n_bits)
    for method in METHODS:
        res = sl.embed_raw(img, payload, method=method, key="k")
        back = sl.extract_raw(res.stego, n_bits, method=method, key="k")
        assert np.array_equal(payload, back), method
        assert res.raw and res.payload_bits == n_bits


def test_raw_payload_is_exact_and_carries_no_header():
    """Raw mode must write the payload and nothing else."""
    img = synthetic_cover(128, 128)
    n_bits = sl.payload_bits_for_bpp(img, 0.25)
    assert n_bits == round(0.25 * 128 * 128)

    payload = deterministic_bits("key", "payload", n_bits)
    raw = sl.embed_raw(img, payload, method="random", key="k")
    assert raw.payload_bits == n_bits
    assert abs(raw.bpp - 0.25) < 1e-9

    # The container mode writes strictly more bits for the same message.
    packed = sl.embed(img, np.packbits(payload).tobytes(), method="random",
                      key="k", compress=False)
    assert packed.payload_bits > raw.payload_bits
    assert container.MAGIC in container.pack(b"x")          # a header exists there
    assert raw.raw is True


def test_raw_rejects_non_binary_input():
    img = synthetic_cover(64, 64)
    raises(ValueError, sl.embed_raw, img, np.array([0, 1, 5], dtype=np.uint8),
           method="random", key="k")


def test_raw_capacity_limit():
    img = synthetic_cover(32, 32)
    capacity_bits = sl.capacity(img, method="random")["capacity_bits"]
    payload = np.zeros(capacity_bits + 1, dtype=np.uint8)
    raises(CapacityError, sl.embed_raw, img, payload, method="random", key="k")
    raises(CapacityError, sl.extract_raw, img, capacity_bits + 1, method="random",
           key="k")


def test_raw_needs_the_right_key():
    img = synthetic_cover(96, 96)
    n_bits = 2000
    payload = deterministic_bits("key", "payload", n_bits)
    res = sl.embed_raw(img, payload, method="random", key="right")
    wrong = sl.extract_raw(res.stego, n_bits, method="random", key="wrong")
    assert not np.array_equal(payload, wrong)


# ---------------------------------------------------------------------------
# deterministic payload generation
# ---------------------------------------------------------------------------
def test_deterministic_payloads_are_reproducible_and_independent():
    a = deterministic_bits("master", "case/a", 4096)
    b = deterministic_bits("master", "case/b", 4096)
    assert np.array_equal(a, deterministic_bits("master", "case/a", 4096))
    assert not np.array_equal(a, b)
    assert 0.45 < a.mean() < 0.55                     # unbiased bits
    assert len(deterministic_bytes("master", "case/a", 37)) == 37


def test_deterministic_payload_is_a_prefix_of_itself():
    """A longer request must extend the shorter one, not replace it."""
    short = deterministic_bits("master", "case", 512)
    long = deterministic_bits("master", "case", 4096)
    assert np.array_equal(short, long[:512])


# ---------------------------------------------------------------------------
# experiment design: per-case keys and payloads
# ---------------------------------------------------------------------------
def _benchmark_module():
    import importlib.util
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "experiments", "benchmark.py")
    spec = importlib.util.spec_from_file_location("benchmark_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_case_material_is_independent_per_cover_and_replicate():
    bench = _benchmark_module()
    first, second = synthetic_cover(96, 96, seed=1), synthetic_cover(96, 96, seed=2)

    id_a, key_a, payload_a = bench.case_material(first, 0, "master")
    id_b, key_b, payload_b = bench.case_material(second, 0, "master")
    id_c, key_c, payload_c = bench.case_material(first, 1, "master")

    assert len({id_a, id_b, id_c}) == 3
    assert len({key_a, key_b, key_c}) == 3
    assert len({payload_a, payload_b, payload_c}) == 3

    # Reproducible from the same inputs, and controlled by the master key.
    assert bench.case_material(first, 0, "master") == (id_a, key_a, payload_a)
    assert bench.case_material(first, 0, "other")[1] != key_a


def test_experiment_covers_do_not_share_an_embedding_pattern():
    """Two covers must not end up with the same positions and the same bits.

    With one fixed key and one fixed payload, every image of the same size gets
    an identical spatial pattern, and a neural detector would learn that
    pattern instead of the embedding algorithm.
    """
    bench = _benchmark_module()
    first, second = synthetic_cover(96, 96, seed=1), synthetic_cover(96, 96, seed=2)
    _id_a, key_a, payload_a = bench.case_material(first, 0, "master")
    _id_b, key_b, payload_b = bench.case_material(second, 0, "master")

    codec, n_bits = get_codec("random"), 4000
    positions_a = codec.positions(first, EmbedParams(key=key_a), limit=n_bits)
    positions_b = codec.positions(second, EmbedParams(key=key_b), limit=n_bits)
    assert not np.array_equal(positions_a, positions_b)

    bits_a = deterministic_bits(payload_a, "payload", n_bits)
    bits_b = deterministic_bits(payload_b, "payload", n_bits)
    assert not np.array_equal(bits_a, bits_b)

    stego_a = sl.embed_raw(first, bits_a, method="random", key=key_a).stego
    stego_b = sl.embed_raw(second, bits_b, method="random", key=key_b).stego
    written_a = stego_a.reshape(-1)[positions_a] & 1
    written_b = stego_b.reshape(-1)[positions_b] & 1
    assert np.array_equal(written_a, bits_a)
    assert not np.array_equal(written_a, written_b)
