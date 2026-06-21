# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
