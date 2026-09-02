# The SGL1 container format

A container is a byte string written into the samples of an image in the order
chosen by the embedding method. Neither the method, nor the key, nor the map
settings are stored inside the image: the receiver has to know them in advance.
Only what is needed to validate and unpack the data is stored.

## Layout

```
preamble (8 bytes; plus 8 parity bytes when ECC is on)
  0..3   magic     "SGL1"
  4      version   1
  5      flags     bit0 COMPRESSED, bit1 ENCRYPTED, bit2 ECC
  6      ecc_nsym  Reed-Solomon parity bytes per block (0..32)
  7      check     lowest byte of CRC32 over bytes 0..6

header body (16 bytes, 44 when encrypted; protected as a single RS block)
  0..3   payload_len  uint32, length of the stored payload
  4..7   plain_len    uint32, length of the original message
  8..11  plain_crc32  uint32, CRC32 of the original message
  12     kdf          key derivation function id (1 = scrypt)
  13..15 reserved
  [16..31  salt   (16 bytes, only when ENCRYPTED)]
  [32..43  nonce  (12 bytes, only when ENCRYPTED)]

payload (RS blocks of 223 bytes when ECC is on)
  message -> UTF-8 -> [zlib] -> [AES-256-GCM] -> payload_len bytes
```

All multi-byte fields are big endian.

## Order of transformations

1. The message is encoded as **UTF-8**. The original `decoder.py` packed each
   character as `ord(ch):08b`, which silently broke for any non-ASCII text.
2. **zlib** compression is applied only when it actually shrinks the data; the
   `COMPRESSED` flag records what happened.
3. **AES-256-GCM** encrypts the payload when a password is given. The key comes
   from scrypt (N = 2^16, r = 8, p = 1, 32 bytes) over the password and a
   16-byte salt. The nonce is 12 random bytes and the 16-byte authentication
   tag is part of `payload_len`.
4. **Reed-Solomon** is applied when `ecc_nsym` is non-zero. The preamble (with a
   fixed 8 parity bytes), the header body (one block) and the payload (blocks of
   223 data bytes) are encoded separately, so the header can be parsed before
   the payload is decoded.

## Four independent checks

| What is verified | How | What it catches |
|---|---|---|
| this is our container at all | magic and version | a foreign image, a wrong key or method |
| the preamble is intact | CRC32 check byte | localised header corruption |
| the message is intact | CRC32 of the plaintext | altered data |
| the message is authentic | AES-GCM tag | tampering, a wrong password |

## Overhead

Without encryption or ECC a container adds **24 bytes**. With encryption it is
68 bytes (salt, nonce, tag). With ECC, add the parity of each block:

```
overhead = 24 + 8 + nsym + (encrypted ? 44 : 0)
payload  = original * (223 + nsym) / 223
```

For comparison, the original `decoder.py` spent 12 bits on every ASCII
character instead of 8 - half the capacity lost to alignment - and carried no
integrity check at all.

## Compatibility

`version` changes whenever the layout changes incompatibly. A reader must
reject an unknown version instead of trying to parse it.
