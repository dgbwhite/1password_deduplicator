# 1Password Duplicate Cleaner – Apply‑Changes Script

## 1. Purpose and Context

This document specifies the behaviour and implementation requirements for the secondary automation script that **applies changes** using the CSV output produced by the primary duplicate‑detection tool.

This script reads a structured CSV file containing suggested actions for each 1Password item (keep, delete, review) and performs the following:

- Identifies which items should be deleted.
- Prompts the user for confirmation.
- Deletes the selected items safely via the `op` CLI.
- Produces a clear console report of actions taken.

This utility exists to separate **analysis** (duplicate detection) from **execution** (applying changes), reducing risk and improving auditability.

## 2. Scope

In scope:

- Reading the dedupe CSV produced by the first script.
- Filtering items based on the suggested actions and user choices.
- Deleting items in 1Password via the `op` CLI.
- Handling confirmations and per‑item logging.

Out of scope:

- Re‑identifying duplicates (handled upstream).
- Editing or modifying items.
- Evaluating correctness of `keep/delete/review` recommendations.

## 3. Assumptions and Dependencies

- The user has run the dedupe detection script first and has a valid CSV.
- CSV columns follow the schema defined by the first tool (including group_id, key, reason, keep_or_delete, item_id, etc.).
- User has 1Password CLI (`op`) installed and authenticated.
- Python 3.9+ or equivalent runtime.
- The user has permission to delete items.

## 4. High‑Level Behaviour

1. Accept input arguments (CSV path, flags).
2. Load and validate the CSV file.
3. Filter rows where `keep_or_delete == "delete"`.
4. Group deletions by duplicate‑group for context.
5. Display a summary of proposed deletions.
6. Ask the user for confirmation.
7. If confirmed, delete the selected items using `op item delete <id> --yes`.
8. Log outcomes to the console.

## 5. Command‑Line Interface Requirements

### 5.1 Arguments

- `--csv <path>` (required)
  - Path to the dedupe report.
- `--yes`
  - Skip confirmation and proceed directly with deletions.
- `--dry-run`
  - Simulate deletions without executing `op` commands.

The script should refuse to run if neither `--yes` nor an interactive confirmation is available.

### 5.2 User Prompts

If `--yes` is not set:

- Show the number of items that will be deleted.
- Prompt: `Proceed with deleting N items? (y/N):`
- Only accept `y` or `Y` as affirmative.

## 6. Functional Requirements

### 6.1 CSV Parsing

The script must:

- Read rows using Python’s `csv.DictReader`.
- Validate that required fields exist:
  - `item_id`
  - `keep_or_delete`
  - `title`
  - `vault`
  - `urls`
  - `group_id`
  - `reason`
- Reject CSVs missing mandatory fields with a clear error.

### 6.2 Filtering Deletion Candidates

Rules:

- Only rows where `keep_or_delete == "delete"` are deletion candidates.
- Rows with `review` or `keep` must be ignored.

### 6.3 Grouping for Display

To improve user trust and transparency:

- Group deletable items by `group_id`.
- For each group, display:
  - Group number
  - Reason (domain+username or key+username)
  - Matching key

Then list each item under the group:

- Item ID
- Title
- Vault
- URLs
- Last updated (if present)

### 6.4 Confirmation Flow

If the user has not passed `--yes`:

- Show the full summary.
- Request confirmation.
- Abort safely if user declines.

### 6.5 Deletion Execution

For each deletion candidate:

- Build the command: `op item delete <item_id> --yes`.
- Run via `subprocess.run` with:
  - `capture_output=True`
  - `text=True`

Deletion results:

- On success (`returncode == 0`): Print `Deleted <id> - <title>`.
- On failure: Print an error including stderr.

### 6.6 Dry Run Mode

If `--dry-run` is set:

- Simulate all deletions but do not call `op`.
- Output lines such as:
  - `DRY-RUN: Would delete <id> - <title>`.

### 6.7 Error Handling

- Missing CSV → exit with error message.
- Malformed rows → warn and skip.
- Missing item_id in a row marked for deletion → warn and skip.
- `op` deletion failures should not abort the script; continue with others.

## 7. Data Structures

### 7.1 CSV Row Structure

The input CSV must contain at least:

- `group_id` (string or int)
- `reason`
- `key`
- `keep_or_delete` (keep/delete/review)
- `item_id`
- `title`
- `vault`
- `urls`
- `username`
- `last_updated`
- `is_newer`
- `linked_apps` (may be empty)

### 7.2 Internal Representation

Recommended internal type:

```
class DeletionCandidate:
    group_id: str
    reason: str
    key: str
    item_id: str
    title: str
    vault: str
    urls: str
    last_updated: str
```

Groups stored as:

```
Dict[str, List[DeletionCandidate]]  # keyed by group_id
```

## 8. Logging and Output Requirements

The script should output:

- Summary of groups and deletable items.
- Clear start/finish messages.
- Deletion results per item.
- Error messages when appropriate.

Use readable formatting, not raw JSON.

## 9. Non‑Functional Requirements

- **Safety**: Must not delete anything without either explicit `--yes` or confirmed input.
- **Transparency**: Always show exactly which items will be deleted.
- **Robustness**: Should handle large CSV files and malformed lines gracefully.
- **Portability**: Script must run on macOS, Linux, and Windows (WSL) where `op` is available.

## 10. Future Enhancements

- Add `--keep-only` mode to apply “keep” flags (e.g., tagging items).
- Add the ability to archive instead of delete.
- Produce an output log file summarising actions.
- Integrate with secure audit logging.

