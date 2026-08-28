# `doors` MCP tool inventory

> **Status: DISCOVERED 2026-04-28** against `http://10.54.7.36:8000/mcp`.
> Schemas live under
> `C:/Users/<your-NT>/.cursor/projects/<proj>/mcps/user-doors/tools/`.

The server exposes 4 tools (no list-modules / no read-object). All of
them are keyed by `module_uuid` — that is the canonical "document UUID"
this skill talks about, and what callers should write into
`doors_mapping.yaml::doors.document_uuid`.

| Operation | Placeholder name | Actual name | UUID arg name |
|---|---|---|---|
| List modules | `doors__list_modules` | *not exposed* | n/a |
| Read module → JSON | `doors__read_module` | `get_doors_module` | `module_uuid` |
| Refresh module cache | *(new)* | `refresh_doors_module` | `module_uuid` |
| Read object → JSON | `doors__read_object` | *not exposed* | n/a (use module read + json_query) |
| Import Excel → module | `doors__import_excel` | `upload_doors_module` | `module_uuid` |
| Upload links Excel | *(new)* | `update_doors_links` | `module_uuid` (default `"links-batch"`) |
| Update single object | `doors__update_object` | *not exposed* | n/a |

## get_doors_module

- Description: *Fetch a DOORS module by module UUID.*
- Args:
    - `module_uuid: str` (required) — mapped from caller's `doors.document_uuid`
    - `user_nt: str` (optional, default `"unknown"`) — caller may pass the local NT username so the server logs who fetched
- Returns: an object (shape varies; use `python <skill>/scripts/doors_helper.py inspect --json-file <path> --depth 3` to explore)
- Used in: Step 7.5b (exploration), Step 8a (pre-upload pull), Step 8d (post-upload verify)
- **Field-name gotcha (verified 2026-05-07 against row 1598 after the
  v1.16.1 push):** the JSON the server returns does **not** expose an
  `Object Text` / `ObjectText` key. Both Object Heading rows and
  ordinary content rows surface their primary text body under
  **`DescriptionOfRequirementRB`**. So:
    - Step 7.5d's anchor lookup (`row.DescriptionOfRequirementRB ==
      "CAN ID and Timing Requirements"`) targets a *heading* row;
    - Step 8d's verification (`row.DescriptionOfRequirementRB`
      against the FSCS we uploaded) targets the *content* row at
      `last_success_abs`. Same field, two semantics.
  If you write a verifier and check `row["Object Text"]` you'll
  get an empty string and incorrectly conclude the upload failed.

## refresh_doors_module

- Description: *Refresh a DOORS module by module UUID.* (forces the server to re-pull from the live DOORS database)
- Args: same as `get_doors_module` (`module_uuid` required, `user_nt` optional)
- When to use: if the agent suspects `get_doors_module` returned a stale cache after a recent edit on the DOORS side. Otherwise prefer `get_doors_module`.
- Returns: same shape as `get_doors_module`.

## upload_doors_module

- Description: *Upload a DOORS module Excel file with per-request user credentials.*
- Args (all required):
    - `module_uuid: str` — target module
    - `user_nt: str` — caller's NT username (the agent should ask the user for this before Step 8c)
    - `password: str` — caller's password (ditto; never log, never store)
    - `file_name: str` — display name; must end `.xlsx`
    - `file_base64: str` — the xlsx bytes, base64-encoded
- Returns: server response (status / row counts).
- Used in: Step 8c (the actual upload).
- **Security**: callers MUST ask the user for `user_nt` / `password` interactively each run. Never echo the password back. Never persist either field to disk.

## update_doors_links

- Description: *Upload a DOORS links Excel file with per-request user credentials.*
- Args:
    - `user_nt: str` (required), `password: str` (required), `file_name: str` (required), `file_base64: str` (required)
    - `module_uuid: str` (optional, default `"links-batch"`)
- Used in: when uploading **link** rows (cross-module references), not regular content. Out of scope for diagcomm-toolkit's Step 8 today.
