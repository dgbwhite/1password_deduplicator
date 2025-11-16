# 1Password Duplicate Login Cleaner – Technical Specification

## 1. Purpose and Context

This document specifies the behaviour and implementation requirements for a command‑line utility that finds and optionally deletes duplicate **Login** items in 1Password, and exports a structured CSV report for review.

Primary goals:

- Identify likely duplicate login entries across one or more 1Password vaults.
- Provide a clear CSV report of duplicates with suggested actions (keep / delete / review).
- Safely, optionally, delete older duplicates.
- Capture and export any **linked mobile/desktop apps** associated with each item.

## 2. Scope

In scope:

- Reading 1Password data via the `op` CLI.
- Interactive vault selection (or scanning all vaults).
- Duplicate detection based on URL/domain + username rules.
- CSV reporting with detailed item metadata and suggested actions.
- Optional automatic deletion of older duplicates per group (key+username only).
- Exporting a human‑readable representation of any **linked apps** associated with an item.

Out of scope for this version:

- GUI front‑end.
- Editing or merging 1Password items.
- Scheduling/daemon behaviour.

## 3. Assumptions and Dependencies

- User has **1Password CLI (****`op`****)** installed and authenticated.
- The script is executed in a shell that can invoke `op`.
- Python 3.9+ (or target runtime language with equivalent standard libraries).
- User has permission to read (and optionally delete) items in the selected vault(s).
- The 1Password item JSON shape follows 1Password 8 conventions, including:
  - `id`, `title`, `overview.title`, `vault.name`, `url`, `urls`, `fields`, `created_at`, `updated_at`, and optionally `apps` / `linkedApps`.

## 4. High‑Level Behaviour

1. **Start‑up and configuration**

   - Load configuration constants (e.g. `CSV_REPORT`, `REMOVE_DUPLICATES`, `MAX_WORKERS`).
   - Parse CLI arguments (currently `--workers`).

2. **Vault selection UI**

   - If environment variable `OP_VAULT` is set, use that vault ID directly and inform the user.
   - Otherwise:
     - Fetch available vaults using `op vault list --format json`.
     - Display a numbered list of vaults (`name` and possibly `id`).
     - Prompt: `Select a vault by number (or press Enter for all vaults):`.
     - If user presses Enter → `vault_id = None` → all vaults are scanned.
     - If user enters a valid number, use that vault’s `id`.

3. **Item ID retrieval**

   - Call `op item list --format json`.
   - If a specific vault is selected, add `--vault <vault_id>`.
   - Parse JSON and collect all `id` values.

4. **Item details retrieval (parallel)**

   - For each item ID, call `op item get <id> --format json`.
   - Execute in parallel using a `ThreadPoolExecutor` with `MAX_WORKERS` workers.
   - Show a progress bar (`tqdm`) labelled “Fetching items”.
   - Collect successful items; skip and warn on failures.

5. **Duplicate index construction**

   - For each item:
     - Extract `username` using canonical rules.
     - Extract full set of URLs.
     - Compute **domain** keys (host part with `www.` stripped).
     - Compute **normalised URL** keys (scheme `https`, host lowercased, query/fragment removed, trailing `/` collapsed).
   - Build two indices:
     1. `by_domain_and_username[(domain, username_key)] -> [items...]`.
     2. `by_key_and_username[(normalised_url, username_key)] -> [items...]`.

6. **Duplicate group creation**

   - For each index, if any key maps to more than one item, create a **duplicate group**:
     - `reason = "domain+username"` or `"key+username"`.
     - `key = (domain, username_key)` or `(normalised_url, username_key)`.
     - `items = [item1, item2, ...]`.

7. **Newness calculation**

   - For each group, determine the **newest** item via `get_best_timestamp`:
     - Prefer `updated_at`; if absent, fall back to `created_at`.
     - Both timestamps may be epoch numbers or ISO strings with or without timezone; normalise to epoch seconds.

8. **CSV report generation**

   - For each group and each item in the group, compute summary fields and suggested action.
   - Write one row per item to a CSV file (default: `duplicate_report.csv`).

9. **Optional deletion of duplicates**

   - If `REMOVE_DUPLICATES` is `True`, perform deletion according to rules in section 7.4.
   - Otherwise, run in **test mode** (no deletion) and print a reminder to inspect the CSV.

## 5. User Interface Requirements

### 5.1 Command‑line interface

- Executable as `python dedupe2_1password.py [--workers N]` (or equivalent launcher).
- Arguments:
  - `--workers N` (int, default = `MAX_WORKERS`)
    - If `N < 1`, warn and force `N = 1`.
- Future‑friendly design: allow additional flags later (e.g. `--delete`, `--csv <path>`, `--dry-run`).

### 5.2 Interactive vault selection (existing feature)

- When `OP_VAULT` is **unset**:
  - Display: “🔐 Fetching available vaults…”
  - List vaults in a numbered fashion, e.g.: `1) Personal  (id: xxx)`.
  - Prompt: `Select a vault by number (or press Enter for all vaults):`.
- Valid inputs:
  - Empty string → “📦 No specific vault selected: scanning all vaults.” → `vault_id=None`.
  - Numeric string corresponding to a vault index → select that vault’s `id` and print: `✅ Selected vault: <name> (id: <id>)`.
- Invalid input:
  - Non‑numeric or out of range → print explanation and re‑prompt.

### 5.3 Progress and logging

- Use clear emojis and plain messages for key phases:
  - “📥 Fetching items…”
  - “🔍 Building duplicate index…”
  - “🧭 Finding potential duplicates…”
  - Success: “✅ No duplicates found. Nice and tidy!”
  - Deletion mode warnings / actions (see section 7.4).
- Use `tqdm` progress bar while fetching items.

## 6. Functional Requirements

### 6.1 Transient error handling for `op`

- Maintain a list of `TRANSIENT_PATTERNS` (e.g. connection reset, timeout strings).
- Function `is_transient_error(stderr: str) -> bool`:
  - Lowercase stderr.
  - Return `True` if any pattern is present.
- Function `run_op(args, retries=3, base_delay=1.0)`:
  - Execute `subprocess.run(["op"] + args, capture_output=True, text=True)`.
  - If `returncode == 0`, return `stdout`.
  - Otherwise:
    - If either this is the last attempt **or** error is not transient → raise `RuntimeError` including stderr.
    - If error is transient and attempts remain → compute `delay = base_delay * attempt` and:
      - Print: `⏳ Transient error on <command> (attempt X/Y), retrying in <delay>s…`.
      - Sleep for `delay` seconds and retry.

### 6.2 URL and domain processing

- `extract_urls_from_item(item) -> set[str]`:

  - Start with `item["url"]` if present.
  - Add:
    - For each element in `item["urls"]`:
      - If dict → consider `u.get("href")`.
      - If string → add directly.
  - Return a **set** (de‑duplicated).

- `site_key_from_url(url) -> Optional[str]`:

  - Parse using `urllib.parse.urlparse`.
  - Extract `netloc` in lower‑case.
  - Strip leading `"www."` if present.
  - Return `host` or `None` if parse fails.

- `normalise_url(url) -> Optional[str]`:

  - Parse with `urlparse(url)`.
  - On parse failure, return original URL as a fallback key.
  - Rules:
    - Force `scheme = "https"`.
    - Use lower‑cased `netloc`.
    - Drop query parameters and fragment.
    - Keep `path`, but collapse `/` to empty.
  - Return `"https://<netloc><path>"` or `None` if input is falsy.

### 6.3 Username extraction

- `extract_username_from_item(item) -> str`:

  - Priority:
    1. Any field in `item["fields"]` where `field["purpose"].upper() == "USERNAME"`.
    2. Any field where lower‑cased `label` is one of `"username"`, `"user name"`, `"login"`.
    3. Top‑level `item["username"]`.
  - Return first non‑empty value found, stripped.
  - If none found, return `""`.

- Normalised username key:

  - `username_key = username.strip().lower()`.

### 6.4 Timestamp parsing and formatting

- `parse_timestamp(value) -> float`:

  - If `value` is int/float → cast to float and return.
  - If string:
    - Strip whitespace.
    - If empty → return `0.0`.
    - If ends with `"Z"` → replace with `+00:00`.
    - Attempt `datetime.fromisoformat`.
      - If the resulting datetime has no timezone → assume UTC.
      - Convert to UTC epoch seconds.
  - On any failure → return `0.0`.

- `get_best_timestamp(item) -> float`:

  - `updated_ts = parse_timestamp(item.get("updated_at"))`.
  - `created_ts = parse_timestamp(item.get("created_at"))`.
  - Return `updated_ts or created_ts` (whichever is non‑zero).

- `format_timestamp(ts: float) -> str`:

  - If `ts` falsy → return `""`.
  - `datetime.fromtimestamp(ts)` and format as `YYYY‑MM‑DD HH:MM:SS` via `isoformat(..., timespec="seconds")`.
  - On failure, return `""`.

### 6.5 Vault and item retrieval

- `choose_vault()` (see UI section) returns either a vault ID string or `None`.

- `get_items(vault_id=None) -> list[str]`:

  - Build `args = ["item", "list", "--format", "json"]`.
  - If `vault_id` is not `None`, append `"--vault", vault_id`.
  - Run `op` via `run_op`.
  - Parse JSON into list of item summaries and return list of `id` values.

- `fetch_one_item(item_id) -> dict`:

  - Call `op item get <id> --format json` via `run_op`.
  - Parse and return JSON dict.

- `fetch_all_items_parallel(ids) -> list[dict]`:

  - Create a `ThreadPoolExecutor(max_workers=MAX_WORKERS)`.
  - Submit `fetch_one_item` for each ID.
  - Wrap iteration with `tqdm(as_completed(...), total=len(ids), desc="Fetching items")`.
  - For each future:
    - On success, append item to list.
    - On exception, log `⚠️ Skipping item <id>: <error>` and continue.

### 6.6 Duplicate index and groups

- `build_duplicate_index(items) -> (by_domain_and_username, by_key_and_username)`:

  - For each `item`:
    - Compute `username_key`.
    - Compute `urls = extract_urls_from_item(item)`.
    - Compute `norm_urls = [normalise_url(u) for u in urls if u]`.
    - Build a set of `domains` via `site_key_from_url` for each URL.
    - For each `domain` in `domains`:
      - Append `item` to `by_domain_and_username[(domain, username_key)]`.
    - For each `nu` in `norm_urls` where `nu` is truthy:
      - Append `item` to `by_key_and_username[(nu, username_key)]`.

- `find_duplicates(by_domain_and_username, by_key_and_username) -> list[Group]`:

  - Initialise `groups = []`.
  - For each `(key, items)` in `by_domain_and_username` with `len(items) > 1`:
    - Append `{ "reason": "domain+username", "key": key, "items": items }`.
  - For each `(key, items)` in `by_key_and_username` with `len(items) > 1`:
    - Append `{ "reason": "key+username", "key": key, "items": items }`.

- `choose_newest_item(items) -> item`:

  - Sort `items` descending by `get_best_timestamp`.
  - Return the first item.

### 6.7 Item summarisation (extended for linked apps)

- `summarise_item(item) -> (title, vault, urls, username, last_updated, linked_apps)`:
  - `title`:
    - Prefer `item["title"]`.
    - Fallback to `item["overview"]["title"]`.
    - Else `""`.
  - `vault`:
    - `item["vault"]["name"]` or `""`.
  - `urls`:
    - Call `extract_urls_from_item(item)`; join sorted set with `", "`.
  - `username`:
    - Call `extract_username_from_item(item)`.
  - `last_updated`:
    - `format_timestamp(get_best_timestamp(item))`.
  - `linked_apps` (new feature):
    - Inspect item for linked applications in at least one of these fields (configurable at implementation time):
      - `item.get("apps")` (preferred for 1Password 8).
      - `item.get("linkedApps")` (if present in some export formats).
    - If the field is a list of dicts, construct a short string for each app such as:
      - `"<platform>: <name>"` or `"<platform>: <name> (<bundleId>)"` where fields exist.
    - Join all app strings with `"; "`.
    - If no apps are found, return `""`.

### 6.8 CSV report generation (including linked apps)

- `write_report(groups)`:
  - Open `CSV_REPORT` in write mode, UTF‑8.
  - Write header row (updated to include `linked_apps`):
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
    - `linked_apps`  **(new)**
  - For each group (`idx` starting at 1):
    - Determine `newest = choose_newest_item(group["items"])` and `newest_id = newest["id"]`.
    - For each `item` in the group:
      - `is_newer = "YES"` iff `item["id"] == newest_id`, else `""`.
      - `keep_or_delete`:
        - If `reason == "domain+username"` → `"review"`.
        - If `reason == "key+username"`:
          - If `is_newer == "YES"` → `"keep"`.
          - Else → `"delete"`.
        - Otherwise → `"review"`.
      - `(title, vault, urls, username, last_updated, linked_apps) = summarise_item(item)`.
      - Write CSV row with all fields.

### 6.9 Deletion behaviour

- Controlled by configuration flag `REMOVE_DUPLICATES` (bool).

  - If `False`:
    - After writing report, print:
      - “🛡️ Test mode: no items were deleted.”
      - “📄 Open '\<CSV\_REPORT>' to review 'review' rows and keep/delete suggestions.”
  - If `True`:
    - Call `delete_duplicates(groups)`.

- `delete_duplicates(groups)`:

  - For each group (with index and `reason`, `key`):
    - Print `"🧹 Group <idx> (<reason> = <key>)"`.
    - If `reason == "domain+username"`:
      - Print that this group is skipped for automatic deletion.
      - For each item, print `REVIEW: <id> - <title> [<vault>] (<urls>)`.
    - If `reason == "key+username"`:
      - Compute `newest` and `newest_id`.
      - Print `Keeping newest: <id> - <title>`.
      - For each older item:
        - Print `Deleting older: <id> - <title> [<vault>] (<urls>)`.
        - Call `run_op(["item", "delete", <id>, "--yes"])`.
        - On failure, print `Failed to delete <id>` with error message.
    - Else:
      - Print that the reason is unknown and no automatic deletion is performed.

## 7. Data Structures

- **Item** (dict as returned by `op item get`), with commonly used fields:

  - `id: str`
  - `title: str`
  - `overview: { title: str }`
  - `vault: { id: str, name: str }`
  - `url: str` (legacy)
  - `urls: list[dict|str]`
  - `fields: list[dict]` (holding username and other login data)
  - `updated_at: str|float|int`
  - `created_at: str|float|int`
  - `apps / linkedApps: list[dict]` (optional; used for linked apps extraction)

- **Duplicate group** (Python dict or equivalent structure):

  - `reason: str` ("domain+username" | "key+username")
  - `key: tuple[str, str]` (e.g. `(domain, username_key)`)
  - `items: list[Item]`

## 8. Error Handling and Logging

- All calls to `op` must use `run_op` to benefit from retry logic.
- If `op vault list` returns no vaults, raise a `RuntimeError` with a clear message.
- If item list for chosen vault(s) is empty, print “No items found. Exiting.” and terminate gracefully.
- When fetching items in parallel, any failure must:
  - Log a warning with item ID.
  - Continue processing remaining items.
- CSV write errors should surface as exceptions and stop the program (to avoid implying a report was generated when it was not).

## 9. Configuration and Extensibility

- Constants (with defaults):

  - `CSV_REPORT = "duplicate_report.csv"`.
  - `REMOVE_DUPLICATES = False`.
  - `MAX_WORKERS = 8`.

- Consider exposing additional options via CLI in future:

  - `--csv <path>` to override report path.
  - `--delete` to toggle `REMOVE_DUPLICATES` to `True`.
  - `--include-empty-usernames` to include groups with missing usernames.
  - `--rule <domain|key|both>` to select duplicate detection rules.

- The linked apps extraction logic should be implemented so that:

  - If 1Password changes the representation of linked apps, only a single helper needs to be updated (`extract_linked_apps_from_item`).
  - The CSV column name remains stable (`linked_apps`).

## 10. Non‑Functional Requirements

- **Performance**: capable of handling several thousand items within a reasonable time using parallel fetches.
- **Security**:
  - Do not log secrets, passwords, or full item contents.
  - Only print high‑level information (title, vault name, URLs, username, linked app names).
- **Reliability**:
  - Robust to transient network or service issues via retry logic.
  - Partial failures in fetching items should not abort the entire run.
- **Testability**:
  - Design so that all helper functions (URL/username parsing, indexing, grouping, CSV writing) are unit‑testable with mocked data.
  - `run_op` should be mockable for offline tests.

## 11. Implementation Notes

- Keep the code modular:
  - `cli.py` or `main()` for argument parsing and orchestration.
  - `op_client.py` for `run_op`, vault and item retrieval.
  - `dedupe.py` for indexing and group creation.
  - `report.py` for CSV generation.
- Ensure the new **linked apps** logic is carefully tested with sample 1Password JSON that includes and excludes app links.
- When recoding in another language, reproduce behaviour faithfully, especially:
  - Vault selection UI and `OP_VAULT` override.
  - Duplicate rules and suggested actions.
  - Retry behaviour and progress reporting.
  - CSV schema including the new `linked_apps` column.

