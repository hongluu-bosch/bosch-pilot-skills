# DOORS MCP tool discovery

The `doors` MCP server at `http://10.54.7.36:8000/mcp` exports its own set
of tool names — they are **not** standardized across DOORS deployments.
This skill therefore performs **tool discovery** the first time it is used
in a new environment, and persists what it found into
[`tool_inventory.md`](./tool_inventory.md).

---

## When to (re)run discovery

Run discovery when:

- This skill has just been added to the project.
- The user upgraded the DOORS MCP server and the previous tool names
  stopped working (e.g. the agent reports `tool not found`).
- `tool_inventory.md` is missing or empty.

---

## Procedure (agent-side)

> **Pre-requisite:** the user has reloaded / restarted Cursor after the
> `doors` entry was added to `~/.cursor/mcp.json`. Verify the agent UI shows
> the `doors` MCP server as connected before continuing.

### Step 1 — list tools

The agent should enumerate the `doors` MCP server's tools. In Cursor this
is done implicitly by the MCP runtime when the server connects; the agent
sees the tools as `doors__<name>`.

If the agent has direct access to a "list tools" facility, use it. Otherwise
ask: "Which tools does the `doors` MCP server expose?" and observe the
auto-injected list of available MCP tools in the next message.

### Step 2 — map operations to actual names

Match each row of the table below to the closest exported tool.

| Operation | Likely keywords | Required args (from caller) |
|---|---|---|
| List modules | `list`, `modules`, `tree` | (none) or `path_prefix` |
| Read module → JSON | `read_module`, `export_module`, `get_module` | `document_uuid` (preferred); fall back to `module_id` / `module_path` if the tool only accepts those |
| Read object → JSON | `read_object`, `get_object` | `object_id` |
| Import Excel → module | `import_excel`, `upload_excel`, `ingest` | `document_uuid` (preferred); plus `file` (xlsx path) |
| Update single object | `update_object`, `patch_object`, `set_attribute` | `object_id`, `attributes` |

> **Note on the document UUID.** Caller skills are asked to fill in a
> `document_uuid` in their `doors_mapping.yaml`. When recording the actual
> tool args in `tool_inventory.md`, document **how the server names that
> field** (e.g. `module_uuid`, `doc_id`, `urn`...) so callers know exactly
> which mapping field to forward.

### Step 3 — record the mapping

Write the discovered names and arg shapes into
[`tool_inventory.md`](./tool_inventory.md). After that, all callers of this
skill can rely on it.

A minimal inventory entry looks like:

```md
## doors__export_module

- Purpose: Operation A — Read module → JSON
- Required args: `module_path: str`
- Optional args: `include_attachments: bool = false`
- Returns: a JSON object with keys `module`, `objects[]`
```

---

## Smoke test

After discovery, verify connectivity end-to-end with a small read:

1. Pick a small known DOORS module (ask the user).
2. Agent calls the read-module tool with that module's path.
3. Save the response to a temporary file under `outputs/` and run:

   ```bash
   python <skill>/scripts/doors_helper.py inspect --json-file outputs/<temp>.json --depth 2
   ```

4. Confirm the response shape looks sane (top-level keys, object counts).

If any of these fail, do **not** advertise the skill as ready. Tell the
user what is broken (network, auth, tool names) and stop.
