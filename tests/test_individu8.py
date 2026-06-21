"""Tests for individu8."""

import pytest

import individu8

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple():
    return {"id": 1, "name": "Alice", "active": True}


@pytest.fixture
def nested():
    return {
        "id": 1,
        "name": "Alice",
        "_meta_id": "system-col",
        "person": {
            "address": [
                {
                    "street": {
                        "name": "Main St",
                        "updated_at": "2024-01-01",
                        "number": {"code": "A1"},
                    },
                },
                {
                    "street": {
                        "name": "Oak Ave",
                        "updated_at": "2024-02-01",
                        "number": {"code": "B2"},
                    },
                },
            ],
        },
    }


# ---------------------------------------------------------------------------
# basic hashing
# ---------------------------------------------------------------------------


def test_dict_returns_str(simple):
    result = individu8(simple)
    assert isinstance(result, str)
    assert len(result) > 0


def test_list_returns_list(simple):
    result = individu8([simple, simple])
    assert isinstance(result, list)
    assert len(result) == 2


def test_deterministic(simple):
    assert individu8(simple) == individu8(simple)


def test_key_order_irrelevant(simple):
    reordered = {"active": True, "name": "Alice", "id": 1}
    assert individu8(simple) == individu8(reordered)


def test_different_values_differ(simple):
    other = {**simple, "name": "Bob"}
    assert individu8(simple) != individu8(other)


def test_array_order_matters(simple):
    a = {**simple, "tags": ["x", "y"]}
    b = {**simple, "tags": ["y", "x"]}
    assert individu8(a) != individu8(b)


# ---------------------------------------------------------------------------
# input types
# ---------------------------------------------------------------------------


def test_json_string_input(simple):
    import json

    assert individu8(simple) == individu8(json.dumps(simple))


def test_yaml_string_input(simple):
    import yaml

    # yaml string input with output="same_as_input" returns a YAML-formatted string —
    # force output="python" to get a plain hash for comparison
    yaml_str = yaml.dump(simple)
    assert individu8(simple, output="python") == individu8(yaml_str, output="python")


def test_invalid_string_raises():
    # "{{{{" is invalid YAML — should raise TypeError with parse error message
    with pytest.raises(TypeError, match="could not be parsed as JSON or YAML"):
        individu8("{{{{")


def test_non_dict_list_string_raises():
    with pytest.raises(TypeError, match="must be a dict or list"):
        individu8('"just a string"')  # valid JSON but not dict/list


def test_non_dict_raises():
    with pytest.raises(TypeError):
        individu8(42)  # type: ignore


# ---------------------------------------------------------------------------
# filter pipeline
# ---------------------------------------------------------------------------


def test_exclude_all_keys_starting_with(nested):
    result = individu8(nested, exclude_all_keys_starting_with=["_meta"])
    # hash should differ from full hash (system col removed)
    assert result != individu8(nested)


def test_exclude_all_keys_ending_with(nested):
    a = individu8(nested, exclude_all_keys_ending_with=["_id"])
    b = individu8({k: v for k, v in nested.items() if not k.endswith("_id")})
    # _meta_id ends with _id so should be excluded
    assert a == b


def test_exclude_all_keys_containing():
    data = {"foo_temp_bar": 1, "keep": 2}
    result = individu8(data, exclude_all_keys_containing=["temp"])
    assert result == individu8({"keep": 2})


def test_exclude_plain_key(simple):
    result = individu8(simple, exclude=["name"])
    assert result == individu8({"id": 1, "active": True})


def test_exclude_jsonpath(nested):
    # exclude "updated_at" only inside person.address[*].street
    result = individu8(
        nested,
        exclude=["person.address[*].street.updated_at"],
    )
    # changing updated_at should not change the hash
    import copy

    changed = copy.deepcopy(nested)
    changed["person"]["address"][0]["street"]["updated_at"] = "CHANGED"
    assert result == individu8(changed, exclude=["person.address[*].street.updated_at"])


def test_include_plain_key(simple):
    result = individu8(simple, include=["id"])
    assert result == individu8({"id": 1})  # only id hashed


def test_include_jsonpath(nested):
    result = individu8(nested, include=["person.address[*].street"])
    assert isinstance(result, str)


def test_exclude_then_include(nested):
    """Excluded fields should not affect hash even when include is used."""
    import copy

    h1 = individu8(
        nested,
        exclude=[
            "person.address[*].street.updated_at",
            "person.address[*].street.number.code",
        ],
        include=["person.address[*].street"],
    )
    changed = copy.deepcopy(nested)
    changed["person"]["address"][0]["street"]["updated_at"] = "CHANGED"
    changed["person"]["address"][0]["street"]["number"]["code"] = "XX"
    h2 = individu8(
        changed,
        exclude=[
            "person.address[*].street.updated_at",
            "person.address[*].street.number.code",
        ],
        include=["person.address[*].street"],
    )
    assert h1 == h2


def test_non_excluded_field_changes_hash(nested):
    import copy

    h1 = individu8(
        nested,
        exclude=["person.address[*].street.updated_at"],
        include=["person.address[*].street"],
    )
    changed = copy.deepcopy(nested)
    changed["person"]["address"][0]["street"]["name"] = "CHANGED"
    h2 = individu8(
        changed,
        exclude=["person.address[*].street.updated_at"],
        include=["person.address[*].street"],
    )
    assert h1 != h2


# ---------------------------------------------------------------------------
# hash algorithms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("algorithm", ["blake2b", "blake2s", "sha256", "md5", "shake128"])
def test_all_algorithms_return_str(simple, algorithm):
    result = individu8(simple, hash_algorithm=algorithm)
    assert isinstance(result, str)
    assert len(result) > 0


def test_algorithms_produce_different_hashes(simple):
    hashes = {
        a: individu8(simple, hash_algorithm=a)
        for a in ["blake2b", "blake2s", "sha256", "md5", "shake128"]
    }
    assert len(set(hashes.values())) == 5  # all different


def test_blake2s_max_length_raises(simple):
    with pytest.raises(ValueError, match="maximum of"):
        individu8(simple, hash_algorithm="blake2s", hash_bytes=33)


def test_sha256_fixed_length(simple):
    # sha256 with default hash_length=14 — truncated to 14 chars
    # use hash_bytes=32 to get the full 43-char output
    result = individu8(simple, hash_algorithm="sha256")
    assert len(result) == 14


def test_sha256_full_length(simple):
    # hash_bytes=32 bypasses hash_length and returns full sha256 output
    result = individu8(simple, hash_algorithm="sha256", hash_bytes=32)
    assert len(result) == 43


def test_md5_fixed_length(simple):
    # md5 with default hash_length=14 — truncated to 14 chars
    result = individu8(simple, hash_algorithm="md5")
    assert len(result) == 14


def test_md5_full_length(simple):
    # hash_bytes=16 bypasses hash_length and returns full md5 output
    result = individu8(simple, hash_algorithm="md5", hash_bytes=16)
    assert len(result) == 22


def test_unsupported_algorithm_raises(simple):
    with pytest.raises(ValueError, match="unsupported hash_algorithm"):
        individu8(simple, hash_algorithm="sha512")  # type: ignore


# ---------------------------------------------------------------------------
# hash length
# ---------------------------------------------------------------------------


def test_hash_length_affects_output(simple):
    h10 = individu8(simple, hash_length=10)
    h20 = individu8(simple, hash_length=20)
    assert len(h20) > len(h10)


def test_no_padding_in_result(simple):
    result = individu8(simple)
    assert "=" not in result


# ---------------------------------------------------------------------------
# json backends
# ---------------------------------------------------------------------------


def test_orjson_and_stdlib_produce_same_hash(simple):
    assert individu8(simple, json_backend="orjson") == individu8(simple, json_backend="stdlib")


def test_orjson_and_stdlib_same_with_nested(nested):
    assert individu8(nested, json_backend="orjson") == individu8(nested, json_backend="stdlib")


def test_unsupported_backend_raises(simple):
    with pytest.raises(ValueError, match="unsupported json_backend"):
        individu8(simple, json_backend="ujson")  # type: ignore


# ---------------------------------------------------------------------------
# output formats
# ---------------------------------------------------------------------------


def test_output_python_dict(simple):
    result = individu8(simple, output="python")
    assert isinstance(result, str)


def test_output_python_list(simple):
    result = individu8([simple], output="python")
    assert isinstance(result, list)


def test_output_json_dict(simple):
    result = individu8(simple, output="json")
    # single hash — json and python are identical for a single dict
    assert isinstance(result, str)


def test_output_json_list(simple):
    import json

    result = individu8([simple, simple], output="json")
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 2


def test_output_yaml_list(simple):
    import yaml

    result = individu8([simple, simple], output="yaml")
    assert isinstance(result, str)
    parsed = yaml.safe_load(result)
    assert isinstance(parsed, list)


def test_output_same_as_input_dict(simple):
    # dict input -> python str
    result = individu8(simple, output="same_as_input")
    assert isinstance(result, str)


def test_output_same_as_input_json_string(simple):
    import json

    result = individu8(json.dumps([simple]), output="same_as_input")
    # input was JSON string of a list -> output should be JSON string
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, list)


def test_output_same_as_input_yaml_string(simple):
    import yaml

    result = individu8(yaml.dump(simple), output="same_as_input")
    # input was YAML string -> output should be YAML string
    assert isinstance(result, str)


def test_unsupported_output_raises(simple):
    with pytest.raises(ValueError, match="unsupported output format"):
        individu8(simple, output="xml")  # type: ignore


# ---------------------------------------------------------------------------
# hash format
# ---------------------------------------------------------------------------


def test_hash_format_base64_default(simple):
    result = individu8(simple)
    # base64 uses A-Z a-z 0-9 + / characters (no padding)
    valid_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    assert all(c in valid_chars for c in result)
    assert "=" not in result


def test_hash_format_hex(simple):
    result = individu8(simple, hash_format="hex")
    # hex uses only 0-9 a-f
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_format_hex_length(simple):
    # default hex: 7 bytes = 14 hex chars
    result = individu8(simple, hash_format="hex")
    assert len(result) == 14


def test_hash_format_hex_hash_bytes(simple):
    # hash_bytes=8 -> 16 hex chars
    result = individu8(simple, hash_format="hex", hash_bytes=8)
    assert len(result) == 16


def test_hash_format_uuid(simple):
    import re

    result = individu8(simple, hash_format="uuid")
    # standard UUID format: 8-4-4-4-12
    assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", result)


def test_hash_format_uuid_is_version_8(simple):
    import uuid

    result = individu8(simple, hash_format="uuid")
    assert uuid.UUID(result).version == 8


def test_hash_format_uuid_always_36_chars(simple):
    result = individu8(simple, hash_format="uuid")
    assert len(result) == 36


def test_hash_format_uuid_deterministic(simple):
    assert individu8(simple, hash_format="uuid") == individu8(simple, hash_format="uuid")


def test_hash_format_uuid_warns_on_hash_length(simple):
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        individu8(simple, hash_format="uuid", hash_length=20)
        assert any("hash_length is ignored" in str(warning.message) for warning in w)


def test_hash_format_uuid_warns_on_hash_bytes(simple):
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        individu8(simple, hash_format="uuid", hash_bytes=32)
        assert any("hash_bytes is ignored" in str(warning.message) for warning in w)


def test_hash_formats_produce_different_strings(simple):
    b64 = individu8(simple, hash_format="base64")
    hex_ = individu8(simple, hash_format="hex")
    uid = individu8(simple, hash_format="uuid")
    # all different representations
    assert b64 != hex_
    assert b64 != uid
    assert hex_ != uid


# ---------------------------------------------------------------------------
# hash_bytes parameter
# ---------------------------------------------------------------------------


def test_hash_bytes_controls_digest_size(simple):
    h8 = individu8(simple, hash_bytes=8)
    h16 = individu8(simple, hash_bytes=16)
    # more bytes = longer base64 string
    assert len(h16) > len(h8)


def test_hash_bytes_exact_length_base64(simple):
    # 8 bytes -> ceil(8*8/6) = 11 base64 chars
    result = individu8(simple, hash_bytes=8)
    assert len(result) == 11


def test_hash_bytes_exact_length_hex(simple):
    # 8 bytes -> 16 hex chars
    result = individu8(simple, hash_format="hex", hash_bytes=8)
    assert len(result) == 16


def test_hash_bytes_and_hash_length_raises(simple):
    with pytest.raises(ValueError, match="specify either hash_length or hash_bytes"):
        individu8(simple, hash_length=20, hash_bytes=8)


# ---------------------------------------------------------------------------
# hash_length as string length
# ---------------------------------------------------------------------------


def test_hash_length_exact_chars(simple):
    for length in [8, 9, 12, 14, 16, 20]:
        result = individu8(simple, hash_length=length)
        assert len(result) == length, f"expected {length} chars, got {len(result)}"


def test_hash_length_non_multiple_of_4(simple):
    # non-multiples of 4 are truncated — result is still exactly hash_length chars
    result = individu8(simple, hash_length=9)
    assert len(result) == 9
