import csv
import subprocess
from tqdm import tqdm

# === CONFIGURATION ===
CSV_FILE = "duplicate_report.csv"   # Must match the file from the first script
ACTION_COLUMN = "action"            # Column that indicates KEEP / DELETE
DELETE_VALUE = "DELETE"             # Rows with this value will be deleted (case-insensitive)
# ======================

def run_op(args):
    """Run an op CLI command and return stdout as text or raise on error."""
    result = subprocess.run(["op"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"op {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout

def load_deletion_list(csv_path):
    """Read the CSV and return a list of items to delete based on the action column."""
    to_delete = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        required_cols = {"item_id", ACTION_COLUMN}
        missing = required_cols - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"CSV is missing required columns: {', '.join(missing)}")

        for row in reader:
            action_raw = row.get(ACTION_COLUMN, "") or ""
            action = action_raw.strip().upper()
            if action != DELETE_VALUE.upper():
                continue  # only delete rows explicitly marked DELETE

            item_id = (row.get("item_id") or "").strip()
            title = (row.get("title") or "").strip()
            url = (row.get("url") or "").strip()
            if not item_id:
                continue

            to_delete.append({
                "id": item_id,
                "title": title,
                "url": url,
                "action": action_raw,
            })

    return to_delete

def ask_dry_run():
    """Ask the user whether to run in dry-run mode."""
    while True:
        answer = input("Run in dry-run mode (no deletions)? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'.")

def delete_items(items, dry_run: bool):
    """Delete items from 1Password based on the provided list."""
    if not items:
        print("✅ No items marked for deletion in the CSV.")
        return

    if dry_run:
        print("🛡️ DRY RUN: no deletions will be performed.")
        print("The following items WOULD be deleted:")
        for item in items:
            print(f" - {item['id']}  |  {item['title']}  |  {item['url']}")
        return

    print("🗑️ Deleting items marked as DELETE in the CSV...")
    for item in tqdm(items, desc="🚮 Deleting", unit="item"):
        try:
            run_op(["item", "delete", item["id"]])
        except Exception as e:
            print(f"⚠️ Failed to delete {item['title']} ({item['id']}): {e}")

    print("✅ Deletion run complete.")

def main():
    print(f"🔐 Reading deletion instructions from '{CSV_FILE}'…")
    try:
        items = load_deletion_list(CSV_FILE)
        print(f"🔎 Found {len(items)} item(s) marked as '{DELETE_VALUE}' in the CSV.")
        dry_run = ask_dry_run()
        delete_items(items, dry_run)
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()