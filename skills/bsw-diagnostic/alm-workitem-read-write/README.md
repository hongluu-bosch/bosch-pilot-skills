# ALM WorkItem Read/Write Skill

This skill provides small Python scripts for reading Bosch ALM WorkItems, updating WorkItem Tags, and uploading or deleting attachments.

## Location

- Skill definition: `.agents/skills/alm-workitem-read-write/SKILL.md`
- Scripts directory: `.agents/skills/alm-workitem-read-write/scripts/`

## Supported Operations

1. Read WorkItem details
2. Update WorkItem Tags directly
3. Safely add or remove Tags with read-before-write flow
4. Upload WorkItem attachments
5. Delete WorkItem attachments

## Scripts

- `get_workitem.py`: read one WorkItem by ID
- `update_workitem_tags.py`: overwrite the `Tags` field with a full value
- `manage_tags.py`: read current `subject`, then add/remove tags and submit as `Tags`
- `upload_attachment.py`: upload a local file as attachment
- `delete_attachment.py`: delete one attachment by attachment ID
- `_wi_http.py`: shared HTTP and JSON output helper

## Base URL

```text
https://cprds.apac.bosch.com/rtc-mb-wi
```

## Common Parameters

All scripts support:

- `--api-key <key>`: override default API key
- `--base-url <url>`: override service base URL
- `--timeout <seconds>`: request timeout
- `--out <path.json>`: custom output JSON path

## Usage Examples

### 1. Read a WorkItem

```powershell
python scripts/get_workitem.py 6741996
```

### 2. Update Tags Directly

Use this only when you already know the full final `Tags` value.

```powershell
python scripts/update_workitem_tags.py 6741996 --json "{\"Tags\":\"12356, bb54856, bb54857, ccb_no_need, bb52625\"}"
```

### 3. Add or Remove Tags Safely

`manage_tags.py` reads the current `subject` field first, computes the new tag list locally, then submits the result through the `Tags` field.

```powershell
python scripts/manage_tags.py 6741996 --add-tags TagA TagB
python scripts/manage_tags.py 6741996 --remove-tags OldTag
python scripts/manage_tags.py 6741996 --add-tags NewTag --remove-tags OldTag --dry-run
```

### 4. Upload an Attachment

```powershell
python scripts/upload_attachment.py 6741996 "C:\000_DATA\DDL\DDL2DTC.docx"
```

### 5. Delete an Attachment

```powershell
python scripts/delete_attachment.py 6741996 3602781
```

## Output Files

Scripts write JSON result files under `output/` by default:

- Read: `output/alm_workitem_get_<id>.json`
- Update Tags: `output/alm_workitem_update_<id>.json`
- Upload attachment: `output/alm_workitem_upload_attachment_<id>_<filename>.json`
- Delete attachment: `output/alm_workitem_delete_attachment_<id>_<attachmentId>.json`

Success rule:

- `ok=true` and HTTP status is `2xx`

Failure rule:

- `ok=false`, missing HTTP status, or non-`2xx`; check `error` or `data`

## Notes

- `update_workitem_tags.py` overwrites the entire `Tags` field.
- Prefer `manage_tags.py` when you only want to add or remove part of the existing tags.
- Attachment deletion is irreversible; read the WorkItem first to confirm the attachment ID.
- The shared HTTP helper includes light automatic retry for transient network failures.
- If you see `401` or `403`, check VPN, connectivity, and API key permission.

## Quick Test Flow

```powershell
python scripts/get_workitem.py 6741996
python scripts/manage_tags.py 6741996 --add-tags 12356 --dry-run
python -c "from pathlib import Path; p=Path('output/alm_attachment_test_6741996.txt'); p.write_text('attachment upload/delete test for workitem 6741996\n', encoding='utf-8'); print(p)"
python scripts/upload_attachment.py 6741996 "output/alm_attachment_test_6741996.txt"
python scripts/delete_attachment.py 6741996 <attachment_id>
```
