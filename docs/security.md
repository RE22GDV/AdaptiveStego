# What the password protects, and what it does not

Steganography hides that a message exists. Encryption hides what it says.
Neither replaces the other, and this document is about the second one: where
the password goes, what an observer can learn from the container, and which of
the two modes to use.

## The password never enters the image

In both modes the password is used only to derive a key, and the key is used
only inside AES-256-GCM. Nothing derived from the password is reversible back
to it, and the password itself appears nowhere in the container - there is a
test that asserts exactly that (`test_the_password_is_never_in_the_container_in_either_mode`).

What *can* travel with the message is the **key material**: the scrypt salt,
the GCM nonce, and the flag that says the payload is encrypted. Those are not
secret - they are meant to be public - but they are informative, and that is
what the second mode removes.

## Two modes

### Stored key material (the default)

    adaptivestego embed -c cover.png -o stego.png -t "secret" --password

    +--------+-------+----------+------------+--------------+
    | ASG1   | flags | lengths  | salt+nonce | ciphertext   |
    |        | ENC   |          | 28 bytes   |              |
    +--------+-------+----------+------------+--------------+

* A fresh random salt and nonce for every message.
* Two encryptions of the same message under the same password differ.
* Anyone who can read the container knows it is encrypted.
* 28 bytes of overhead.

This is the textbook arrangement and the right default. The randomness is
where its safety comes from: a fresh nonce every time is what AES-GCM needs,
and a fresh salt per message is what stops one scrypt computation from being
reused against many messages.

### Derived key material

    adaptivestego embed -c cover.png -o stego.png -t "secret" \
        --password --no-key-material

    +--------+-------+----------+--------------+
    | ASG1   | flags | lengths  | ciphertext   |
    |        | (none)|          |              |
    +--------+-------+----------+--------------+

The salt and the nonce are computed from the password and from the header
fields the receiver reads before decrypting - the payload length, the message
length and the CRC32 of the message:

    context = "ASG1" | version | flags | ecc | payload_len | plain_len | crc32
    salt    = HMAC-SHA256(password, "ASG1/derived-salt/v1"  | context)[:16]
    key     = scrypt(password, salt)
    nonce   = HMAC-SHA256(key,      "ASG1/derived-nonce/v1" | context)[:12]

The context is also passed to GCM as associated data, so a receiver that
rebuilds it from tampered header fields gets an authentication failure rather
than a plausible wrong answer.

* Nothing in the container says a password was used. The header is byte for
  byte the shape of an unencrypted one, and 28 bytes shorter.
* The receiver needs exactly what it needed before: the password.
* Extraction discovers the mode instead of being told it - see
  [detection.md](detection.md).

## What derived mode costs

Three things, and they are the reason it is not the default.

**It is deterministic.** The same message under the same password produces the
same container, every time. An observer who sees two identical containers
learns that the two messages were identical. Stored mode cannot leak that.

**Nonce uniqueness rests on the header.** AES-GCM is broken outright by a
repeated nonce under one key - not weakened, broken, losing both
confidentiality and integrity for the two messages involved. Here the nonce is
a function of the password and the context, so two messages collide only if
they have the same lengths *and* the same CRC32. That does not happen by
accident (2^-32 per pair), but CRC32 collisions are trivial to construct for
someone who chooses the plaintexts. **Do not use derived mode for messages an
adversary can influence.**

**The salt is not per-message random.** It is still per-message - the context
varies - but it is a deterministic function of the password, so an attacker
who knows the header fields can precompute scrypt for a guessed password
against that particular message. Stored mode's random salt makes that work
useless for any other message; derived mode makes it useless for any other
*header*, which is weaker.

Both modes cost the same to attack by guessing the password itself: scrypt at
N = 2^16, r = 8, p = 1, about 64 MiB and a few tenths of a second per guess.

## Which to use

| You want | Use |
| --- | --- |
| Encryption, normally | stored (the default) |
| The container not to advertise that it is encrypted | derived |
| To send many messages you did not write yourself | stored |
| The last 28 bytes of capacity | derived |

Note what derived mode does *not* hide. Ciphertext has the entropy of
ciphertext, so a container whose payload does not decompress and does not
match its checksum still looks like encrypted data to anyone who parses it -
`adaptivestego detect` says so itself. What derived mode removes is the
explicit statement, the salt and the nonce, not the statistical fact.

## What neither mode protects

* **The fact that the image was touched.** That is what the detectors in
  [detection.md](detection.md) are for, and they work regardless of whether
  the payload is encrypted.
* **The parameters.** The method, the key, the bits per sample and the map
  settings are not in the image. They protect placement, not content, and the
  receiver has to know them.
* **The message length.** `plain_len` is in the header in both modes.
* **Anything after an attack.** The message does not survive JPEG
  re-encoding, resizing, or noise beyond what the error correction covers.
