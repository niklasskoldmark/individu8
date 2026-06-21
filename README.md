# individu8

Deterministic hashing of Python dicts, lists, and JSON/YAML strings.

```python
from individu8 import individu8

individu8({"id": 1, "name": "Alice"})
# "FszF+jYmhYS17K"

individu8([{"id": 1}, {"id": 2}])
# ["GICezwtC7+vhEA", "DxgzKROIe5u0sQ"]
```

## Why

- **Stable across runs** — same data always produces the same hash, regardless of key insertion order
- **Flexible filtering** — exclude volatile fields (timestamps, system columns) before hashing
- **Multiple input formats** — pass a dict, list, JSON string, or YAML string
- **Multiple output formats** — base64 (default), hex, or UUID v8
- **Multiple hash algorithms** — blake2b (default), blake2s, sha256, md5, shake128
- **Predictable length** — `hash_length` controls the exact number of characters returned
- **Fast** — uses orjson for serialisation by default (5-10x faster than stdlib json)

## Install

```bash
pip install individu8
# or
uv add individu8
```

## Usage

### Basic

```python
from individu8 import individu8

# hash a dict — returns exactly hash_length characters (default 14)
individu8({"id": 1, "name": "Alice"})
# "FszF+jYmhYS17K"

# hash a list — returns a list of hashes in the same order
individu8([{"id": 1}, {"id": 2}])
# ["GICezwtC7+vhEA", "DxgzKROIe5u0sQ"]

# hash a JSON string — identical to dict input
individu8('{"id": 1, "name": "Alice"}')
# "FszF+jYmhYS17K"

# hash a YAML string — identical to dict input
individu8("id: 1\nname: Alice")
# "FszF+jYmhYS17K"
```

### Filtering

Filtering is applied as a pipeline in this order:

1. `exclude_all_keys_starting_with` / `ending_with` / `containing` — removes matching keys recursively at any depth
2. `exclude` — removes specific keys or jsonpath paths from the full document
3. `include` — narrows to only the specified keys or paths

```python
# exclude system/metadata keys at any depth
individu8(data, exclude_all_keys_starting_with=["_meta", "_dlt"])
individu8(data, exclude_all_keys_ending_with=["_at", "_id"])
individu8(data, exclude_all_keys_containing=["temp"])

# exclude specific top-level keys
individu8(data, exclude=["updated_at", "created_at"])

# exclude a nested key using jsonpath — only removes "code" inside this specific path,
# not other keys named "code" elsewhere in the document
individu8(data, exclude=["person.address[*].street.number.code"])

# hash only specific fields
individu8(data, include=["id", "name"])

# combine: hash only street data, excluding volatile subfields
individu8(
    data,
    exclude=["person.address[*].street.updated_at"],
    include=["person.address[*].street"],
)
```

### Hash length

`hash_length` controls the exact number of characters in the returned string.
The library computes as many bytes as needed internally and truncates to exactly
`hash_length` characters — you always get exactly what you asked for.

```python
individu8(data, hash_length=8)    # 8 chars
individu8(data, hash_length=14)   # 14 chars (default)
individu8(data, hash_length=20)   # 20 chars
individu8(data, hash_length=32)   # 32 chars
```

For clean alignment with base64 encoding use multiples of 4 (12, 16, 20, 24) —
other values work fine but the last 1–3 characters of entropy are discarded by
truncation.

For expert control over digest size in bytes, use `hash_bytes` instead:

```python
individu8(data, hash_bytes=16)   # 16-byte digest → 22 base64 chars
individu8(data, hash_bytes=32)   # 32-byte digest → 43 base64 chars
```

### Hash format

```python
# base64 (default) — URL-safe ASCII, no padding
individu8(data)
# "FszF+jYmhYS17K"

# hex — lowercase hexadecimal, hash_bytes * 2 characters
individu8(data, hash_format="hex")
# "19ccbe8d3d2f6b"

# UUID v8 — deterministic, RFC 9562 compliant, always 36 characters
# 122 bits of entropy (128 minus 6 version/variant bits)
# accepted anywhere a UUID is expected
individu8(data, hash_format="uuid")
# "6b5dc393-b52a-8ea0-a003-4f6986d2db77"
```

UUID v8 is the RFC 9562 "custom" variant — designed for exactly this use case
where you want deterministic, content-based UUIDs using your own hash algorithm.

### Hash algorithms

```python
individu8(data, hash_algorithm="blake2b")   # default — fast, modern, recommended
individu8(data, hash_algorithm="blake2s")   # 32-bit optimised, max hash_bytes=32
individu8(data, hash_algorithm="sha256")    # widely compatible, matches git/AWS
individu8(data, hash_algorithm="md5")       # legacy, used for ETags/checksums
individu8(data, hash_algorithm="shake128")  # SHA-3, matches dlt _dlt_id format
```

### Output structure

Controls what wraps the hash string(s) — separate from `hash_format` which
controls how each individual hash is encoded.

```python
individu8(data, output="same_as_input")  # default — matches input type
individu8(data, output="python")         # always str or list[str]
individu8(data, output="json")           # always a JSON string
individu8(data, output="yaml")           # always a YAML string
```

### JSON backend

```python
individu8(data, json_backend="orjson")   # default — 5-10x faster
individu8(data, json_backend="stdlib")   # stdlib json, no extra dependencies
```

Both backends produce identical hashes for the same input.

## Supported input types

The following Python types are handled automatically when they appear as values
in the data being hashed:

| Type | Serialised as |
|---|---|
| `Decimal` | string (avoids float precision loss) |
| `datetime` / `date` / `time` | ISO 8601 string |
| `UUID` | string |
| `bytes` | base64 string |
| `namedtuple` | dict via `_asdict()` |
| `@dataclass` | dict via `dataclasses.asdict()` |
| `Enum` | `.value` |
| pydantic `BaseModel` | dict via `.model_dump()` |
| objects with `.asdict()` | dict via `.asdict()` |

## Development

```bash
git clone https://github.com/niklasskoldmark/individu8
cd individu8
uv sync
uv run pytest
uv run ruff check src/ tests/
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Powered by

- [jsonpath-ng](https://github.com/pacman-packages/jsonpath-ng) — jsonpath filtering
- [orjson](https://github.com/ijl/orjson) — fast JSON serialisation
- [pyyaml](https://github.com/yaml/pyyaml) — YAML parsing


## License

MIT — see [LICENSE](LICENSE).