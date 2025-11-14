
# 1Password Duplicate Finder & Cleaner (CLI-Based)

This project contains two Python scripts designed to identify and safely remove duplicate items from a 1Password vault using the official `op` command-line tool.

It is built for users who have accumulated hundreds or thousands of items over many years and want a safe, auditable, and semi-automated workflow for cleaning their vault.

These scripts are ideal for:
- Users with large, messy 1Password vaults
- Users migrating from another password manager
- Users who want bulk detection and bulk deletion
- Privacy-conscious technical and semi-technical users
- Anyone comfortable using the command line

Both scripts run locally and do not transmit vault data anywhere.

## ⚠️ Important – Back up 1Password before using this

These scripts **modify and delete items in your 1Password account**. Although they’re designed to be cautious (CSV review, dry-run mode, newest-item detection), they still operate on live data.

Before you use them, you should:

1. **Understand how 1Password backups work.**  
   1Password automatically backs up your account data on their servers, but *deleted vaults cannot be restored*, and item deletion is permanent. You can, however, archive items and restore previous versions of individual items. See:  
   - 1Password backups (official support): https://support.1password.com/backups/

2. **Optionally create your own local export/backup.**  
   If you want an extra safety net, export your vault (or account) from the 1Password desktop app before running any bulk changes. 1Password supports exporting to formats like **1PUX** (for re-importing into 1Password) and **CSV** (for use in other tools). See:  
   - How to export your data from the 1Password desktop app: https://support.1password.com/export/

3. **Test on a non-critical vault first.**  
   If you have multiple vaults, consider creating a small “test” vault, copy a few representative items into it, and run the full workflow (dedupe → CSV review → apply script) there first.

> **You use these scripts at your own risk.** Always review the generated `duplicate_report.csv` carefully, run the delete/apply script in **dry-run mode** first, and only then perform real changes once you’re satisfied.

## Contents
- `dedupe2_1password.py` — scans a vault, detects duplicates, and exports a CSV report.
- `delete_from_csv_1password.py` — reads the CSV and performs deletions (with an interactive dry-run mode).

## What the Scripts Do

### `dedupe2_1password.py`
This script:
1. Connects to 1Password via the CLI (`op`).
2. Retrieves all items in the selected vault.
3. Loads them in parallel with a progress bar.
4. Normalises full URLs (not just domains).
5. Applies additional logic for edge cases like localhost URLs or items with missing URLs.
6. Finds duplicates using multi-pass matching (URL, title+username, title-only).
7. Identifies the newest item in any duplicate cluster.
8. Writes a `duplicate_report.csv` containing recommended actions.

**No deletions occur in this script.**

### `delete_from_csv_1password.py`
This script:
1. Reads your `duplicate_report.csv`.
2. Extracts items flagged for deletion.
3. Asks whether to run in dry-run mode.
4. Performs deletions via `op item delete <item_id>`.
5. Provides a progress bar and completion summary.

## Prerequisites
- 1Password CLI installed
- Signed in via `eval $(op signin)`
- Python 3.9+
- Python packages: `tqdm`, `python-dateutil`

## Installation
Install 1Password CLI (macOS):
```sh
brew install --cask 1password-cli
```

Install Python dependencies:
```sh
pip3 install tqdm python-dateutil
```

## How to Use the Scripts

### Step 1 — Generate duplicate report
```sh
python3 dedupe2_1password.py
```
This produces `duplicate_report.csv`.

### Step 2 — Review the CSV
Open it in any spreadsheet tool. Only rows marked `DELETE` will be acted on later.

### Step 3 — Delete duplicates
```sh
python3 delete_from_csv_1password.py
```
When prompted:
- Press Enter for dry run
- Type `n` to perform actual deletions

## Vault Selection
Set your vault with an environment variable:
```sh
OP_VAULT="My Vault" python3 dedupe2_1password.py
```
The deletion script does not require vault selection.

## Safety Features
- No deletions without confirmation
- CSV export allows full audit
- Dry-run mode
- Newest-item detection
- Parallel loading for speed

## Known Limitations
- URL matching depends on stored data quality
- Missing timestamps reduce accuracy
- Large vaults may take time due to CLI latency

## Recommended Workflow
1. Scan one vault at a time.
2. Review CSV manually.
3. Run dry-run deletion.
4. Execute real deletion.
5. Re-scan to confirm cleaning.

## Contributing
Pull requests are welcome.

## License
MIT License
