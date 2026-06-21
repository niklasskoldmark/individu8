import base64
import copy
import dataclasses
import hashlib
import json as _stdlib_json
import math
import re
import sys
import uuid as _uuid_mod
import warnings
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, Literal
from uuid import UUID

import jsonpath_ng.ext as jp
import orjson
import yaml

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

_BLAKE2S_MAX_DIGEST_BYTES = 32
"""Maximum digest size in bytes for the BLAKE2s algorithm."""

_DEFAULT_HASH_LENGTH = 14
"""Default returned hash string length in characters (base64, no padding)."""

_DEFAULT_HEX_DIGEST_BYTES = 7
"""Default digest size in bytes for hex format (produces 14 hex chars)."""

_UUID_DIGEST_BYTES = 16
"""UUID always requires exactly 16 bytes (128 bits, 122 usable after version/variant)."""


# ---------------------------------------------------------------------------
# module-level helpers — defined once, not redefined on every call
# ---------------------------------------------------------------------------


def _encode(obj: Any) -> Any:
    """Encode types not natively supported by json/orjson.

    Called by the JSON backend for any value it cannot serialise natively.
    Each branch converts a known Python type to a JSON-safe equivalent.

    Returns:
        A JSON-serializable representation of the input object.

    Raises:
        TypeError: If the object type cannot be serialized to JSON.

    """
    # Decimal: serialise as string to avoid float precision loss
    if isinstance(obj, Decimal):
        return str(obj)
    # datetime/date/time: serialise as ISO 8601 string e.g. "2024-01-01T12:00:00"
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    # UUID: serialise as string e.g. "550e8400-e29b-41d4-a716-446655440000"
    if isinstance(obj, UUID):
        return str(obj)
    # bytes: serialise as base64 string
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    # objects with a public asdict() method: a convention some libraries use
    # to signal "I know how to serialise myself to a dict"
    if hasattr(obj, "asdict"):
        return obj.asdict()
    # namedtuple: Python's namedtuple generates _asdict() on every instance
    if hasattr(obj, "_asdict"):
        return obj._asdict()
    # @dataclass decorated classes: recursively convert to dict
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    # Enum: use the underlying value e.g. MyEnum.FOO -> "foo"
    if isinstance(obj, Enum):
        return obj.value
    # pydantic BaseModel: checked dynamically to avoid a hard pydantic import —
    # if pydantic isn't installed sys.modules.get returns None and we skip this
    m = sys.modules.get("pydantic")
    if m is not None and isinstance(obj, m.BaseModel):
        return obj.model_dump()
    # nothing matched — let the JSON backend raise a clear error
    msg = f"`{obj!r}` is not JSON serializable"
    raise TypeError(msg)


def _should_exclude_key(
    k: str,
    starting_with: list[str] | None,
    ending_with: list[str] | None,
    containing: list[str] | None,
) -> bool:
    """Return True if key k matches any pattern-based exclusion rule.

    Returns:
        True if key matches any exclusion pattern, False otherwise.

    """
    return (
        (starting_with is not None and any(k.startswith(p) for p in starting_with))
        or (ending_with is not None and any(k.endswith(p) for p in ending_with))
        or (containing is not None and any(p in k for p in containing))
    )


def _apply_pattern_exclude(
    obj: Any,
    starting_with: list[str] | None,
    ending_with: list[str] | None,
    containing: list[str] | None,
) -> Any:
    """Recursively remove all keys matching any pattern-based exclusion rule.

    Returns:
        The object with matching keys removed.

    """
    if isinstance(obj, dict):
        return {
            k: _apply_pattern_exclude(v, starting_with, ending_with, containing)
            for k, v in obj.items()
            if not _should_exclude_key(k, starting_with, ending_with, containing)
        }
    if isinstance(obj, list):
        return [
            _apply_pattern_exclude(item, starting_with, ending_with, containing) for item in obj
        ]
    return obj


def _apply_plain_exclude(obj: Any, plain_keys: set[str]) -> Any:
    """Recursively remove all occurrences of plain_keys from a nested structure.

    Returns:
        The object with matching keys removed.

    """
    if isinstance(obj, dict):
        return {
            k: _apply_plain_exclude(v, plain_keys) for k, v in obj.items() if k not in plain_keys
        }
    if isinstance(obj, list):
        return [_apply_plain_exclude(item, plain_keys) for item in obj]
    return obj


def _remove_by_jsonpath(obj: Any, expr: Any) -> Any:
    """Return obj with all values matching the jsonpath expr removed.

    Uses jsonpath_ng's built-in filter mechanism — avoids depending on
    the internal string representation of full_path which changed in 1.8.0.

    Returns:
        The object with matching paths removed.

    """
    obj = copy.deepcopy(obj)
    for match in expr.find(obj):
        match.full_path.filter(lambda _: True, obj)
    return obj


def _serialise_orjson(obj: Any) -> bytes:
    """Serialise obj to canonical JSON bytes using orjson (fast path).

    orjson is 5-10x faster than stdlib json. OPT_SORT_KEYS ensures key order
    never affects the hash. OPT_NON_STR_KEYS allows non-string dict keys.

    Returns:
        Canonical JSON bytes representation of obj.

    """
    return orjson.dumps(obj, default=_encode, option=orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS)


def _serialise_stdlib(obj: Any) -> bytes:
    """Serialise obj to canonical JSON bytes using stdlib json (compatibility path).

    ensure_ascii=False preserves non-ASCII characters as-is (e.g. Swedish å ä ö).
    separators=(",", ":") produces compact JSON with no whitespace.
    sort_keys=True ensures key order never affects the hash.

    Returns:
        Canonical JSON bytes representation of obj.

    """
    return _stdlib_json.dumps(
        obj,
        default=_encode,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest_to_uuid8(digest: bytes) -> str:
    """Format a digest as a UUID version 8 (custom) string.

    UUID v8 is the RFC 9562 custom UUID variant. Of the 128 bits, 6 are
    reserved for version (4 bits set to 0x8) and variant (2 bits set to 0b10),
    leaving 122 bits of usable entropy from the digest.

    Always uses the first 16 bytes of the digest regardless of digest length.

    Returns:
        A UUID v8 string in standard 8-4-4-4-12 format e.g.
        "6b5dc393-b52a-8ea0-a003-4f6986d2db77".

    """
    b = bytearray(digest[:_UUID_DIGEST_BYTES])
    # set version 8 (custom) — high nibble of byte 6
    b[6] = (b[6] & 0x0F) | 0x80
    # set RFC 4122 variant — high 2 bits of byte 8
    b[8] = (b[8] & 0x3F) | 0x80
    return str(_uuid_mod.UUID(bytes=bytes(b)))


# ---------------------------------------------------------------------------
# main function
# ---------------------------------------------------------------------------


def individu8(
    data: dict | list | str,
    hash_length: int = 14,
    exclude_all_keys_starting_with: list[str] | None = None,
    exclude_all_keys_ending_with: list[str] | None = None,
    exclude_all_keys_containing: list[str] | None = None,
    exclude: list[str] | None = None,
    include: list[str] | None = None,
    output: Literal["same_as_input", "python", "json", "yaml"] = "same_as_input",
    hash_format: Literal["base64", "hex", "uuid"] = "base64",
    hash_algorithm: Literal["blake2b", "blake2s", "sha256", "md5", "shake128"] = "blake2b",
    hash_bytes: int | None = None,
    json_backend: Literal["orjson", "stdlib"] = "orjson",
) -> str | list[str]:
    """Return a deterministic hash of a Python dict, list, or a JSON/YAML string.

    Hash includes key names and values, ordered by key name.
    Accepts dicts, lists of dicts, or strings (parsed as JSON first, then YAML).
    Returns the same type as the input — a single hash for a dict, a list of
    hashes for a list, in the same order.

    Filtering is applied as a pipeline in this order:
      1. exclude_all_keys_starting_with / ending_with / containing — pattern-based,
         removes matching keys recursively at any depth across the whole document.
      2. exclude — removes specific keys or jsonpath paths from the full document.
      3. include — narrows to only the specified keys or paths.

    For surgical removal of keys only at a specific path (e.g. only remove "code"
    inside "person.address[*].street.number" but not elsewhere), use jsonpath
    syntax in exclude — e.g. "person.address[*].street.number.code".
    The exclude_all_keys_* parameters always apply recursively to the entire
    document regardless of where the key appears.

    Args:
      data: a dict, a list of dicts, or a JSON/YAML string to hash.
        When a list is provided, returns a list of hashes in the same order.
      hash_length: length of the returned hash string in characters (default 14).
        The hash is computed internally with enough bytes to produce at least
        hash_length characters, then truncated to exactly hash_length characters.
        For clean alignment with base64 encoding use multiples of 4 (e.g. 12, 16,
        20, 24) — other values work fine but the last 1-3 characters of entropy
        are discarded by truncation.
        Ignored when hash_format="uuid" (always returns 36 chars) or
        hash_format="hex" — use hash_bytes instead for hex to get predictable
        character counts (hash_bytes * 2 chars).
        Ignored if hash_bytes is specified.
        Ignored for sha256 and md5 which have fixed output lengths.
      exclude_all_keys_starting_with: remove all keys whose name starts with
        any of these strings, at any depth. Example: ["_dlt", "_meta"]
      exclude_all_keys_ending_with: remove all keys whose name ends with
        any of these strings, at any depth. Example: ["_at", "_id"]
      exclude_all_keys_containing: remove all keys whose name contains
        any of these strings, at any depth. Example: ["temp", "cache"]
      exclude: optional list of key names or jsonpath expressions to remove
        before hashing. Applied before include.
        Example: ["updated_at", "person.address[*].street.number.code"]
      include: optional list of key names or jsonpath expressions selecting
        which values to hash. When None, all keys are hashed.
        Example: ["person.address[*].street"]
      output: controls the structure of the returned value.
        "same_as_input" (default) returns a Python str/list when input was a
        dict/list, JSON string when input was a JSON string, and YAML string
        when input was a YAML string.
        "python" always returns str or list[str].
        "json"   always returns a JSON string.
        "yaml"   always returns a YAML string.
        Note: for a single dict input, "json" and "python" are identical —
        a bare hash string requires no further serialisation.
      hash_format: encoding format of the returned hash string (default "base64").
        "base64" — URL-safe base64, no padding. Length controlled by hash_length
          or hash_bytes.
        "hex"    — lowercase hexadecimal. Length is always hash_bytes * 2 chars.
          Use hash_bytes to control length; hash_length is ignored.
        "uuid"   — UUID version 8 (custom) format per RFC 9562, e.g.
          "6b5dc393-b52a-8ea0-a003-4f6986d2db77". Always 36 chars (32 hex + 4
          dashes). Uses 16 bytes (122 bits of entropy after version/variant bits).
          hash_length and hash_bytes are ignored — a warning is issued if either
          is explicitly set.
      hash_algorithm: hash algorithm to use (default "blake2b").
        "blake2b"  — fast, modern, recommended for most use cases.
        "blake2s"  — like blake2b but optimised for 32-bit platforms;
          max hash_bytes is 32 for blake2s.
       "sha256"   — widely used, matches git, AWS signatures, and most
          external systems. Always produces 32 bytes internally; the returned
          string length is still controlled by hash_length (default 14 chars).
          Use hash_bytes=32 to get the full 43-char output.
        "md5"      — legacy, not cryptographically secure but widely used
          for checksums and ETags. Always produces 16 bytes internally; the
          returned string length is still controlled by hash_length (default 14
          chars). Use hash_bytes=16 to get the full 22-char output.
        "shake128" — variable-length SHA-3; use this if you need to match
          the exact format used in other systems that use SHAKE-128.
      hash_bytes: alternative to hash_length — specifies the digest size in bytes
        directly, for users who think in terms of entropy rather than string length.
        The returned string length depends on hash_format:
          base64: ceil(hash_bytes * 8 / 6) chars (before truncation)
          hex:    hash_bytes * 2 chars exactly
          uuid:   always 36 chars (hash_bytes is ignored for uuid)
        Cannot be combined with hash_length — raises ValueError if both are set
        to non-default values.
      json_backend: JSON serialisation backend to use (default "orjson").
        "orjson" — 5-10x faster than stdlib, recommended for high-volume use.
        "stdlib" — Python's built-in json module, no extra dependencies.
          Use when maximum compatibility is needed or orjson is unavailable.
        Both backends produce identical hashes for the same input.

    Returns:
      a single hash string when data is a dict or JSON/YAML object string,
      or a list of hash strings when data is a list or JSON/YAML array string,
      unless output is "json" or "yaml" in which case a list is always
      returned as a single serialised string.

    Raises:
      TypeError: if data is a string that cannot be parsed as JSON or YAML,
        or if data is not a dict or list after parsing.
      ValueError: if an unsupported hash_algorithm, output, hash_format, or
        json_backend is specified; if hash_length and hash_bytes are both set;
        or if hash_bytes exceeds the maximum for the selected algorithm.

    """
    # warn if hash_length or hash_bytes are set alongside hash_format="uuid" —
    # uuid always uses 16 bytes and always returns 36 chars
    if hash_format == "uuid":
        if hash_bytes is not None:
            warnings.warn(
                "hash_bytes is ignored when hash_format='uuid' — "
                "uuid always uses 16 bytes (122 bits of entropy).",
                UserWarning,
                stacklevel=2,
            )
        if hash_length != _DEFAULT_HASH_LENGTH:
            # 14 is the default — only warn if explicitly changed
            warnings.warn(
                "hash_length is ignored when hash_format='uuid' — "
                "uuid always returns 36 characters.",
                UserWarning,
                stacklevel=2,
            )

    # resolve digest size in bytes
    if hash_format == "uuid":
        # uuid always needs exactly 16 bytes
        digest_size = _UUID_DIGEST_BYTES
    elif hash_format == "hex":
        # hex: hash_bytes controls length directly; hash_length is irrelevant
        digest_size = hash_bytes if hash_bytes is not None else _DEFAULT_HEX_DIGEST_BYTES
    else:
        # base64: resolve from hash_bytes or hash_length
        if hash_bytes is not None and hash_length != _DEFAULT_HASH_LENGTH:
            msg = "specify either hash_length or hash_bytes, not both"
            raise ValueError(msg)
        digest_size = hash_bytes if hash_bytes is not None else math.ceil(hash_length * 6 / 8)

    # track input format before parsing so output="same_as_input" can match it
    input_format = "python"
    # parse strings as JSON first, then fall back to YAML
    if isinstance(data, str):
        try:
            data = _stdlib_json.loads(data)
            input_format = "json"
        except _stdlib_json.JSONDecodeError:
            try:
                data = yaml.safe_load(data)
                input_format = "yaml"
            except yaml.YAMLError as e:
                msg = f"data string could not be parsed as JSON or YAML: {e}"
                raise TypeError(msg) from e
        if not isinstance(data, (dict, list)):
            msg = f"parsed data must be a dict or list, got {type(data).__name__}"
            raise TypeError(msg)

    # recurse over lists, preserving order — each item hashed independently,
    # then the list of hashes is formatted according to output
    if isinstance(data, list):
        hashes = [
            individu8(
                item,
                hash_length,
                exclude_all_keys_starting_with,
                exclude_all_keys_ending_with,
                exclude_all_keys_containing,
                exclude,
                include,
                "python",  # inner calls always return plain str — outer call handles format
                hash_format,
                hash_algorithm,
                hash_bytes,
                json_backend,
            )
            for item in data
        ]
        use_format = input_format if output == "same_as_input" else output
        if use_format == "json":
            return _stdlib_json.dumps(hashes, ensure_ascii=False)
        if use_format == "yaml":
            return yaml.dump(hashes, allow_unicode=True, default_flow_style=False)
        return hashes

    if not isinstance(data, dict):
        msg = f"data must be a dict, list, or string, got {type(data).__name__}"
        raise TypeError(msg)

    # start with the full dict — the filter functions build new structures
    # rather than mutating, so the original data is never modified
    to_hash: Any = dict(data)

    # pipeline step 1: pattern-based exclusions (fastest, no jsonpath parsing needed)
    if (
        exclude_all_keys_starting_with
        or exclude_all_keys_ending_with
        or exclude_all_keys_containing
    ):
        to_hash = _apply_pattern_exclude(
            to_hash,
            exclude_all_keys_starting_with,
            exclude_all_keys_ending_with,
            exclude_all_keys_containing,
        )

    # pipeline step 2: exclude — must happen before include narrows the structure,
    # so that jsonpaths still match their full paths in the original document shape
    if exclude:
        # split exclude list into plain key names (fast recursive dict filtering)
        # and jsonpath expressions (structural removal via jsonpath-ng) —
        # detected by presence of dots, brackets, or wildcards
        plain_keys = {e for e in exclude if not re.search(r"[.\[\]*?@]", e)}
        jp_exprs = [jp.parse(e) for e in exclude if re.search(r"[.\[\]*?@]", e)]
        if plain_keys:
            to_hash = _apply_plain_exclude(to_hash, plain_keys)
        for expr in jp_exprs:
            to_hash = _remove_by_jsonpath(to_hash, expr)

    # pipeline step 3: include — extract only the values at the specified paths,
    # keyed by their full path string so sort_keys produces stable ordering
    if include is not None:
        projection = {}  # keyed by full path string for stable sort_keys ordering
        for expr in [jp.parse(e) for e in include]:
            for match in expr.find(to_hash):
                projection[str(match.full_path)] = match.value
        to_hash = projection

    # serialise to canonical JSON bytes — sorted keys ensure key order never
    # affects the hash; non-ASCII characters preserved as-is (e.g. Swedish å ä ö)
    if json_backend == "orjson":
        serialised = _serialise_orjson(to_hash)
    elif json_backend == "stdlib":
        serialised = _serialise_stdlib(to_hash)
    else:
        msg = f"unsupported json_backend: {json_backend!r}"
        raise ValueError(msg)

    # hash the serialised bytes using the selected algorithm
    if hash_algorithm == "blake2b":
        # BLAKE2b: fast, modern, designed for data integrity and identity hashing
        digest = hashlib.blake2b(serialised, digest_size=digest_size).digest()
    elif hash_algorithm == "blake2s":
        # BLAKE2s: like BLAKE2b but optimised for 32-bit platforms; max 32 bytes
        if digest_size > _BLAKE2S_MAX_DIGEST_BYTES:
            msg = (
                f"blake2s supports a maximum of {_BLAKE2S_MAX_DIGEST_BYTES} bytes, "
                f"got {digest_size}"
            )
            raise ValueError(msg)
        digest = hashlib.blake2s(serialised, digest_size=digest_size).digest()
    elif hash_algorithm == "sha256":
        # SHA-256: fixed 32-byte output, widely used in external systems
        digest = hashlib.sha256(serialised).digest()
    elif hash_algorithm == "md5":
        # MD5: fixed 16-byte output, legacy but widely used for checksums/ETags —
        # not cryptographically secure
        digest = hashlib.md5(serialised).digest()  # noqa: S324
    elif hash_algorithm == "shake128":
        # SHAKE-128: variable-length SHA-3 — use to match other systems using SHAKE-128
        digest = hashlib.shake_128(serialised).digest(digest_size)
    else:
        msg = f"unsupported hash_algorithm: {hash_algorithm!r}"
        raise ValueError(msg)

    # encode digest to the requested hash_format
    if hash_format == "uuid":
        # UUID v8: deterministic, 122 bits of entropy, standard 36-char format
        result = _digest_to_uuid8(digest)
    elif hash_format == "hex":
        # lowercase hex: hash_bytes * 2 characters, no truncation needed
        result = digest.hex()
    else:
        # base64: URL-safe ASCII, no padding, truncated to exactly hash_length chars
        result = base64.b64encode(digest).decode("ascii").rstrip("=")
        if hash_bytes is None:
            # truncate to exactly the requested character length
            result = result[:hash_length]

    # resolve output format — if "same_as_input", use the format detected during parsing
    use_format = input_format if output == "same_as_input" else output

    # single hash string needs no further encoding regardless of json/python —
    # only lists benefit from json/yaml wrapping
    if use_format in {"python", "json"}:
        return result
    if use_format == "yaml":
        return yaml.dump(result, allow_unicode=True, default_flow_style=False)
    msg = f"unsupported output format: {use_format!r}"
    raise ValueError(msg)
