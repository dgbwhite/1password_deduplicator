# 1Password Duplicate Management – End-to-End Architecture

## 1. Overview

This document describes the **end-to-end architecture** for managing duplicate 1Password Login items using two cooperating command-line tools:

1. **Duplicate Detection & Reporting Script** (`dedupe2_1password.py`)
2. **Apply Changes Script** (`op_dedupe_apply_changes.py`)

Together, they implement a safe, auditable workflow:

- **Analyse**: Scan 1Password, detect likely duplicates, and generate a structured CSV report with recommendations.
- **Decide & Approve**: Human reviews the CSV and adjusts any suggested actions.
- **Execute**: Apply changes (primarily deletions) in a controlled, confirmable manner.

The design intentionally separates **analysis** from **execution** to reduce risk and make it easy to review and roll back decisions.

---

## 2. High-Level Flow

1. **User runs Duplicate Detection script**
   - Selects a vault or all vaults.
   - Script fetches items using 1Password CLI (`op`).
   - Identifies duplicate groups based on URL/domain and username.
   - Produces a CSV report with `keep/delete/review` suggestions and metadata.

2. **User reviews and edits CSV**
   - Opens report in a spreadsheet tool.
   - Optionally edits the `keep_or_delete` column (and any notes) to fine-tune actions.

3. **User runs Apply Changes script**
   - Points it at the updated CSV.
   - Script filters rows marked `delete`.
   - Shows a grouped summary of planned deletions.
   - User confirms or cancels.
   - On confirmation, script deletes items via `op item delete`.

4. **Post-run review**
   - Console output serves as an execution log.
   - CSV acts as a durable record of both recommendations and final actions.

---

## 3. Components and Responsibilities

### 3.1 Duplicate Detection & Reporting Script

**Purpose**: Discover duplicate Login items and generate a detailed report.

**Key responsibilities**:

- **Vault discovery and selection**
  - Read `OP_VAULT` env var (optional shortcut).
  - Otherwise, list vaults and prompt the user to choose a single vault or all vaults.

- **Item retrieval**
  - List items for the selected scope.
  - Fetch full details for each item in parallel, with progress bar and transient error handling.

- **Data extraction and normalisation**
  - Extract `username`, URL(s), domain(s), and timestamps from each item.
  - Normalise URLs (key-based) and domains (host-based) for consistent comparison.
  - Extract `linked_apps` metadata (e.g. mobile/desktop app associations) when present.

- **Duplicate detection**
  - Build indices keyed by `(domain, username)` and `(normalised_url, username)`.
  - Identify keys with more than one item as duplicate groups.
  - Determine the newest item in each group using `updated_at` / `created_at`.

- **Recommendation logic**
  - For each group, classify each item as:
    - `keep` (usually the newest item for `key+username` groups).
    - `delete` (older items in `key+username` groups).
    - `review` (all items in `domain+username` groups and any non-standard cases).

- **CSV report generation**
  - Emit a row per item in each group, including:
    - Group metadata (`group_id`, `reason`, `key`).
    - Item identifiers (`item_id`, title, vault).
    - URLs, username, timestamps.
    - `keep_or_delete` recommendation.
    - `is_newer` flag.
    - `linked_apps` metadata.

- **Optional automatic deletion (direct mode)**
  - If configured, can immediately delete items based on recommendations.
  - For the end-to-end architecture, this mode is generally **disabled** so that the second script handles execution.

---

### 3.2 Apply Changes Script

**Purpose**: Safely apply deletion decisions based on the dedupe CSV.

**Key responsibilities**:

- **CSV ingestion and validation**
  - Read dedupe report via `csv.DictReader`.
  - Validate mandatory columns (e.g. `item_id`, `keep_or_delete`, `group_id`, `reason`, `key`, `title`, `vault`).

- **Candidate selection**
  - Filter rows where `keep_or_delete == "delete"`.
  - Ignore `keep` and `review` rows.

- **Grouping and summarisation**
  - Group deletion candidates by `group_id`.
  - For each group, display:
    - `reason` and `key` (explain why these items are considered duplicates).
    - Each candidate’s ID, title, vault, URLs, and last_updated timestamp.

- **Confirmation flow**
  - If `--yes` is not provided:
    - Display total number of deletions and group breakdown.
    - Prompt user to confirm.
  - If `--dry-run` is set:
    - Simulate deletions and print “would delete” messages without invoking `op`.

- **Deletion execution**
  - For each confirmed deletion candidate:
    - Issue `op item delete <id> --yes`.
    - Log success or error per item.

- **Result reporting**
  - Provide a clear summary at the end:
    - Number of attempted deletions.
    - Number of successful deletions.
    - Number of failures (with brief errors).

---

## 4. Data Flow and Interfaces

### 4.1 External Interfaces

- **1Password CLI (`op`)**
  - Vault list: `op vault list --format json`.
  - Item list: `op item list --format json [--vault <id>]`.
  - Item get: `op item get <id> --format json`.
  - Item delete: `op item delete <id> --yes`.

- **CSV File** (shared between scripts)
  - Written by the detection script.
  - Read (and optionally edited by the user) before being consumed by the apply script.

### 4.2 CSV Contract

The CSV schema is the **contract** between the two tools. At minimum, it includes:

- `group_id`
- `reason`
- `key`
- `keep_or_delete`
- `item_id`
- `title`
- `vault`
- `urls`
- `username`
- `last_updated`
- `is_newer`
- `linked_apps`

The apply script relies primarily on:

- `keep_or_delete`
- `item_id`
- `group_id`
- `reason`
- `key`
- `title`
- `vault`
- `urls`

The user is free to modify `keep_or_delete` in the CSV to override default recommendations.

---

## 5. Execution Sequence

### 5.1 Overall Sequence Diagram (Conceptual)

1. **User → Detection Script**: Run `python dedupe2_1password.py`.
2. **Detection Script → op**: List vaults; get items; fetch full item JSON.
3. **Detection Script**: Build duplicate groups, compute recommendations.
4. **Detection Script → Filesystem**: Write `duplicate_report.csv`.
5. **User → CSV**: Open, inspect, tweak `keep_or_delete` values, save.
6. **User → Apply Script**: Run `python op_dedupe_apply_changes.py --csv duplicate_report.csv [--dry-run|--yes]`.
7. **Apply Script → Filesystem**: Read CSV.
8. **Apply Script**: Filter rows for deletion, group for display, prompt.
9. **User → Apply Script**: Confirm deletions.
10. **Apply Script → op**: Delete items.
11. **Apply Script → User**: Print summary.

---

## 6. Error Handling Across the Flow

### 6.1 Detection Script

- **Transient CLI errors** (e.g. network issues):
  - Handled by `run_op` retry logic.
- **Item-level failures**:
  - Logged and skipped; other items still processed.
- **No duplicates found**:
  - Script prints a friendly message and exits.
- **CSV write failure**:
  - Script raises an error and exits; no partial report implied.

### 6.2 Apply Script

- **Missing or malformed CSV**:
  - Fails fast with a clear explanation.
- **Missing `item_id` on a deletion row**:
  - Warn and skip that row.
- **`op` deletion failure for specific item**:
  - Log error and continue with remaining items.
- **User cancels at confirmation step**:
  - Exit without side effects.

---

## 7. Security and Safety Considerations

- **Authentication**:
  - Both scripts rely on 1Password CLI’s authentication model and do not manage secrets themselves.

- **Least information output**:
  - Logs show only non-sensitive metadata (title, vault name, URLs, username, linked apps label), no passwords or secure fields.

- **Separation of duties**:
  - Analysis and execution are separated into two tools and two distinct moments in time.
  - CSV review step acts as a human approval gate.

- **Dry-run and confirm-before-delete**:
  - Apply script supports dry-run mode and explicit user confirmation before making changes.

---

## 8. Deployment and Usage Patterns

### 8.1 Typical Usage

1. Install Python and 1Password CLI.
2. Log in with `op` and ensure access to required vaults.
3. Run the detection script periodically (e.g. monthly) to generate a CSV.
4. Review CSV manually.
5. Run the apply script in `--dry-run` first.
6. Run again with `--yes` when comfortable with the plan.

### 8.2 Packaging and Distribution

- Package both scripts together as a small CLI toolkit:
  - `fho-op-dedupe detect`
  - `fho-op-dedupe apply`
- Provide a README that explains the full workflow, including:
  - How to interpret the CSV.
  - How to override recommendations safely.

---

## 9. Extensibility

The architecture is designed for incremental enhancement without breaking the core contract.

Possible extensions:

- **Tagging instead of deletion**:
  - Apply script could add tags or notes instead of deleting, based on CSV columns.

- **Archiving mode**:
  - Instead of deleting, move items to a special "Archive" vault.

- **Additional actions**:
  - New CSV columns could drive actions like "rename", "merge", "move between vaults".

- **Audit logging**:
  - Apply script could write a secondary log (JSON/CSV) of actions taken, including timestamps and outcomes.

- **Configurable duplicate rules**:
  - Detection script could accept configuration (flags or config file) to change matching rules (e.g. ignore subdomains, match on email domains only, etc.).

---

## 10. Summary

The combined architecture provides a **safe, transparent, and maintainable** way to:

- Identify duplicate 1Password logins.
- Present clear, editable recommendations in CSV form.
- Apply deletions only after explicit human review and confirmation.

This separation of analysis and execution, combined with explicit contracts (CSV schema) and robust error handling, makes it suitable for regular housekeeping of 1Password vaults with minimal risk.

