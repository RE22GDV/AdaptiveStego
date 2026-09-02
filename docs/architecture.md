# Architecture

## Module map

```mermaid
flowchart TB
    subgraph ui["Interfaces"]
        GUI["gui.py<br/>tkinter, 3 languages"]
        CLI["cli.py<br/>argparse"]
    end

    subgraph api_layer["Public API"]
        API["api.py<br/>embed / extract / capacity"]
    end

    subgraph payload["Payload pipeline"]
        CONT["container.py<br/>ASG1 header, CRC"]
        CRYPTO["crypto.py<br/>scrypt + AES-256-GCM"]
        ECC["ecc.py<br/>Reed-Solomon"]
        BITIO["bitio.py<br/>bytes to bits"]
    end

    subgraph placement["Placement"]
        CODECS["codecs/<br/>6 methods"]
        MAPS["maps.py<br/>integer complexity maps"]
        PRNG["prng.py<br/>keyed Philox order"]
    end

    subgraph engine["Engine"]
        CORE["core.py<br/>replace / match"]
        IO["image_io.py<br/>lossless, verified"]
    end

    subgraph eval["Evaluation"]
        METRICS["metrics.py<br/>PSNR, SSIM, BER"]
        ATTACKS["attacks.py<br/>12 distortions"]
        ANALYSIS["analysis.py<br/>chi2, SPA"]
        SELFTEST["selftest.py<br/>determinism digest"]
    end

    GUI --> API
    CLI --> API
    GUI --> eval
    CLI --> eval
    API --> CONT
    API --> BITIO
    API --> CODECS
    API --> IO
    CONT --> CRYPTO
    CONT --> ECC
    CODECS --> MAPS
    CODECS --> PRNG
    CODECS --> CORE
```

## Embedding

```mermaid
flowchart LR
    MSG["message<br/>str or bytes"] --> U8["UTF-8"]
    U8 --> Z{"compress?"}
    Z -->|smaller| ZLIB["zlib"]
    Z -->|no gain| SKIP[" "]
    ZLIB --> E{"password?"}
    SKIP --> E
    E -->|yes| AES["scrypt + AES-256-GCM"]
    E -->|no| PLAIN[" "]
    AES --> HDR["ASG1 header<br/>magic, flags, CRC32"]
    PLAIN --> HDR
    HDR --> R{"ECC?"}
    R -->|yes| RS["Reed-Solomon"]
    R -->|no| NORS[" "]
    RS --> BITS["bit stream"]
    NORS --> BITS

    COVER["cover image"] --> MASK["clear the low bits"]
    MASK --> MAP["complexity map<br/>integer arithmetic"]
    MAP --> BANDS["quantise into bands"]
    KEY["key"] --> TIE["keyed Philox labels"]
    BANDS --> ORDER["order: band desc, then label"]
    TIE --> ORDER
    ORDER --> WRITE["write bits<br/>replace or +/-1"]
    BITS --> WRITE
    COVER --> WRITE
    WRITE --> STEGO["stego image<br/>PNG or BMP"]
```

The receiver runs the same map on the stego image. Because the map ignores
exactly the bits that embedding may change, it comes out identical and the
order of positions is reproduced without any side information.

## Extraction

```mermaid
flowchart LR
    STEGO["stego image"] --> ORDER2["rebuild the order<br/>same map, same key"]
    ORDER2 --> P1["read 8 bytes"]
    P1 --> MAGIC{"magic ASG1<br/>and check byte"}
    MAGIC -->|no| FAIL["no message, or<br/>wrong key/method"]
    MAGIC -->|yes| HEAD["read the header body<br/>lengths, CRC, salt, nonce"]
    HEAD --> GROW["extend the order to<br/>the announced payload"]
    GROW --> PAY["read the payload"]
    PAY --> RS2["Reed-Solomon"]
    RS2 --> DEC["AES-GCM"]
    DEC --> UNZ["zlib"]
    UNZ --> CRC{"CRC32 matches?"}
    CRC -->|no| BAD["data was altered"]
    CRC -->|yes| OUT["message"]
```

## Why the order of positions is computed lazily

A message rarely fills an image. Ordering every sample of a 12 megapixel photo
to write a few kilobytes wastes almost all of the work, so each codec can
produce only the first N positions:

| Codec | Full ordering | First N positions |
|---|---|---|
| `sequential` | `arange(n)` | `arange(N)` |
| `random`, `matching` | stable argsort of n keyed labels | partition to the N smallest labels, then sort those |
| `edge`, `adaptive`, `adaptive-matching` | lexsort by (band, label) | histogram of the bands finds the cut-off band; everything above it is taken whole and only the boundary band is ranked |

Both shortcuts return exactly the prefix of the full ordering, ties included -
the test suite checks that for every codec and every limit, and the determinism
digest is unchanged by the optimisation.

## Layers and their rules

| Layer | Rule it must obey |
|---|---|
| `maps.py` | integer arithmetic only; the same result on every platform |
| `prng.py` | only the raw Philox stream; the permutation is implemented here |
| `container.py` | never trust the input: magic, version, CRC and tag are all checked |
| `core.py` | knows nothing about images or maps, only bits and positions |
| `image_io.py` | refuses lossy formats and re-reads what it wrote |
| `codecs/` | a codec is only an ordering rule; the writing loop is shared |
