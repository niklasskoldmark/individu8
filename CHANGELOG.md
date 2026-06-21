# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-06-21

### Added
- Module is now callable — `import individu8; individu8(data)` works directly
- `hash_format` parameter: `"base64"` (default), `"hex"`, `"uuid"` (UUID v8, RFC 9562)
- `hash_bytes` parameter — expert alternative to `hash_length` for specifying digest size in bytes
- UUID v8 support via `_digest_to_uuid8()` — deterministic, 122 bits of entropy, RFC 9562 compliant

### Changed
- `hash_length` now controls the exact character length of the returned string (default 14)
  rather than digest size in bytes. **Breaking change** — hashes differ from 0.1.0.
- All internal constants now use `_` prefix

### Fixed
- `_remove_by_jsonpath` now uses jsonpath_ng's built-in `filter` mechanism,
  fixing compatibility with jsonpath_ng 1.8.0

## [0.1.0] - 2025-06-21

### Added
- Initial release
- `individu8()` function for deterministic hashing of dicts, lists, and JSON/YAML strings
- Filter pipeline: `exclude_all_keys_starting_with`, `exclude_all_keys_ending_with`,
  `exclude_all_keys_containing`, `exclude`, `include`
- Jsonpath support in `exclude` and `include` via jsonpath-ng
- Hash algorithms: `blake2b` (default), `blake2s`, `sha256`, `md5`, `shake128`
- JSON backends: `orjson` (default, fast), `stdlib` (compatibility)
- Output formats: `same_as_input` (default), `python`, `json`, `yaml`
- YAML string input support via pyyaml
