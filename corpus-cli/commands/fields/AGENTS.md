# commands/fields/

Implements the `corpus field` CLI group for the soft-column field registry.

## Purpose

Fields are named keys that plugins/operations write into `documents.metadata_json`.
The `field_definitions` table only *declares* them; the physical values live in the
existing `metadata_json` column. No migration is needed to add a field.

## Subcommands

- `corpus field list` — show declared fields
- `corpus field create --name X --applies-to all|plugin [--description]` — declare a field
- `corpus field delete --name X` — remove the declaration (existing values are kept)
- `corpus field missing --name X [--source S] [--limit N]` — documents lacking the field
- `corpus field set --name X --source S --id ID --value <json>` — write a value

## Rules

- `--applies-to` is validated against `plugin_manifests.keys()` (plus `all`).
- Field names must match `^[a-z][a-z0-9_]*$` (safe in `json_extract` paths).
- Writing a value for an undeclared field raises `ValueError` (FAIL LOUDLY) —
  create the field first.

## register.py

`register(plugin_manifests) -> CommandManifest`
Called once at startup after plugin discovery. Returns a Click group with subcommands.
