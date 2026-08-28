---
name: alm-workitem-read-write
description: Read Bosch ALM WorkItems(Epic/Story/Task), update WorkItem Tags, and upload or delete attachments. Use this skill whenever the user asks to inspect a specific ALM/CCA WorkItem, update Tags on a WorkItem, or manage WorkItem attachments by ID.
---

# ALM WorkItem Read/Write

This skill provides Python scripts for Bosch ALM WorkItem operations and writes structured JSON results for each execution.

Base URL:

```text
https://cprds.apac.bosch.com/rtc-mb-wi
```

Run commands from the skill root directory.

## Supported Operations

1. Read WorkItem details

```text
GET /get/workitem/{workitem_id}
```

Script:

```powershell
python scripts/get_workitem.py 6741996
```

2. Update WorkItem Tags directly

```text
POST /post/UpdateWorkItem/{workitem_id}
```

Script:

```powershell
python scripts/update_workitem_tags.py 6741996 --json "{\"Tags\":\"BB52625\"}"
```

3. Safely add or remove Tags

`manage_tags.py` reads the current WorkItem `subject`, computes the updated tag list locally, and submits the final value through the `Tags` field.

Scripts:

```powershell
python scripts/manage_tags.py 6741996 --add-tags TagA TagB
python scripts/manage_tags.py 6741996 --remove-tags OldTag
python scripts/manage_tags.py 6741996 --add-tags NewTag --remove-tags OldTag --dry-run
```

4. Delete a WorkItem attachment

```text
POST /post/UpdateWorkItemAttachment/{workitem_id},delete,{attachment_id}
```

Script:

```powershell
python scripts/delete_attachment.py 6741996 3602781
```

5. Upload a WorkItem attachment

```text
POST /post/UpdateWorkItemAttachment/{workitem_id}
multipart/form-data, default field name: file_name
```

Script:

```powershell
python scripts/upload_attachment.py 6741996 "C:\000_DATA\DDL\DDL2DTC.docx"
```

## Script List

- `scripts/get_workitem.py`
- `scripts/update_workitem_tags.py`
- `scripts/manage_tags.py`
- `scripts/delete_attachment.py`
- `scripts/upload_attachment.py`
- `scripts/_wi_http.py`

## Parameters

Common parameters supported by all scripts:

- `--api-key <key>`: override the default API key
- `--base-url <url>`: override the default base URL
- `--timeout <seconds>`: request timeout in seconds
- `--out <path.json>`: custom output JSON path

Additional parameters for `update_workitem_tags.py`:

- `--json <json_string>`: pass a JSON payload directly
- `--json-file <path.json>`: load payload from a JSON file
- Use exactly one of these options, and the payload must be a JSON object

Additional parameters for `upload_attachment.py`:

- `file`: local file to upload
- `--field-name <name>`: multipart field name, default is `file_name`

## Output Files

By default, scripts write JSON result files to `output/`:

- Read WorkItem: `output/alm_workitem_get_<id>.json`
- Update Tags: `output/alm_workitem_update_<id>.json`
- Delete attachment: `output/alm_workitem_delete_attachment_<id>_<attachmentId>.json`
- Upload attachment: `output/alm_workitem_upload_attachment_<id>_<filename>.json`

Success rule:

- `ok=true` and HTTP status is `2xx`

Failure rule:

- `ok=false` or HTTP status is not `2xx`; check `error` or `data`

## Usage Notes

1. Do not expose the API key in user-facing responses.
2. `update_workitem_tags.py` overwrites the full `Tags` value, so confirm the final value before running it.
3. Prefer `manage_tags.py` when the user wants to add or remove a subset of existing tags.
4. Attachment deletion is irreversible; read the WorkItem first to confirm the attachment ID.
5. Upload attachment requests may occasionally hit transient connection errors.
6. The shared HTTP helper includes light automatic retry for transient network failures.
7. If you see `401` or `403`, check VPN, network connectivity, and API key permission.
8. If you see `404`, verify the WorkItem ID or attachment ID.

## Recommended Validation

Read-only connectivity test:

```powershell
python scripts/get_workitem.py 6741996
```

Safe Tag update dry run:

```powershell
python scripts/manage_tags.py 6741996 --add-tags TestTag --dry-run
```

Attachment upload/delete round-trip test:

```powershell
python -c "from pathlib import Path; p=Path('output/alm_attachment_test_6741996.txt'); p.write_text('attachment upload/delete test for workitem 6741996\n', encoding='utf-8'); print(p)"
python scripts/upload_attachment.py 6741996 "output/alm_attachment_test_6741996.txt"
python scripts/delete_attachment.py 6741996 <attachment_id>
```
