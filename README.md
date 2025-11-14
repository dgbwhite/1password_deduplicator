# 1Password Duplicate Finder & Cleaner (CLI-Based)

## Table of Contents
- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Warning: Back Up Your Vault](#warning-back-up-your-vault)
- [How the Scripts Work](#how-the-scripts-work)
- [Usage](#usage)
- [Vault Selection](#vault-selection)
- [Safety Features](#safety-features)
- [Known Limitations](#known-limitations)
- [Recommended Workflow](#recommended-workflow)
- [Recent Updates](#recent-updates)
- [License](#license)

---

## Overview

This project contains two Python scripts designed to identify and safely remove duplicate items from a 1Password vault using the official `op` command-line tool.

It is built for users who have accumulated hundreds or thousands of items and want a safe, auditable, semi‑automated workflow for cleaning their vault.

---

## Prerequisites

- 1Password CLI installed  
- Signed in via `eval $(op signin)`  
- Python 3.9+  
- Python packages: `tqdm`, `python-dateutil`

---

## Warning: Back Up Your Vault

These scripts modify your 1Password data.  
Before using them:

- Understand 1Password backups: https://support.1password.com/backups/  
- Optionally export your vault: https://support.1password.com/export/  
- Test on a non‑critical vault first.

---

## How the Scripts Work

### `op_dedupe_report.py`
- Scans a vault  
- Fetches items in parallel  
- Normalises and compares full URLs  
- Handles localhost and missing URLs  
- Identifies newest duplicates  
- Outputs `duplicate_report.csv`  

### `op_apply_csv_actions.py`
- Reads the CSV  
- Applies manual title/URL fixes  
- Archives items marked `ARCHIVE`  
- Deletes items marked `DELETE`  
- Supports dry‑run mode  

---

## Usage

### Step 1 — Generate report
```sh
python3 op_dedupe_report.py
```

### Step 2 — Review CSV

### Step 3 — Apply changes
```sh
python3 op_apply_csv_actions.py
```

---

## Vault Selection

The report script prompts you interactively to select a vault.

---

## Safety Features

- No deletions without confirmation  
- CSV review step  
- Dry‑run mode  
- Parallel loading  
- Newest‑item detection  

---

## Known Limitations

- Dependent on data quality  
- Missing timestamps reduce accuracy  
- CLI item fetches are slow by design  

---

## Recommended Workflow

1. Scan one vault  
2. Review CSV  
3. Run apply script in dry‑run  
4. Run real apply  
5. Re‑scan  

---

## Recent Updates

- Added interactive vault selection  
- Added ARCHIVE action support  
- Improved URL/title matching  
- Better `url_or_title_key` generation  
- Newest column now blank instead of NO  
- Apply script now updates edited fields  
- README backup warnings added  

---

## License

MIT License
