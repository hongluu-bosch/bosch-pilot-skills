# Phase 4 — DOORS

Phase 4 reads `outputs/fscs/FSCS_19.txt` and `inputs/doors_mapping.yaml`
and builds a DOORS-native Excel upload file.

## Input

- `outputs/fscs/FSCS_19.txt`
- `inputs/doors_mapping.yaml`

## Output

- `outputs/doors/doors_upload_19.xlsx`
- `outputs/doors/doors_upload_report.txt`

## Credentials

First time on a machine, have the operator prime the OS keychain:

```bash
python scripts/fscs/doors/doors_sync.py \
    --user-nt <NT> --password <pwd> --save-credentials --no-upload
```

Subsequent runs only need `--user-nt <NT>`.
