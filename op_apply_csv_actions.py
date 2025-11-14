import csv
import subprocess
from tqdm import tqdm

# === CONFIGURATION ===
CSV_FILE = "duplicate_report.csv"   # Must match the file from the first script
ACTION_COLUMN = "action"            # Column that indicates KEEP / DELETE / ARCHIVE
DELETE_VALUE = "DELETE"
ARCHIVE_VALUE = "ARCHIVE"
# ======================


def run_op(args):
    """Run an op CLI command and return stdout as text or raise on error."""
    result = subprocess.run(["op"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"op {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def load_from_csv(csv_path):
    """
    Read the CSV and return:
    - updates: all rows where we should apply title/url changes (KEEP + ARCHIVE + anything not DELETE)
    - deletes: rows where action == DELETE
    - archives: rows where action == ARCHIVE
    """
    updates = []
    deletes = []
    archives = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        required_cols = {"item_id", ACTION_COLUMN, "title", "url"}
        missing = required_cols - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"CSV is missing required columns: {', '.join(missing)}")

        for row in reader:
            action_raw = row.get(ACTION_COLUMN, "") or ""
            action = action_raw.strip().upper()

            item_id = (row.get("item_id") or "").strip()
            title = (row.get("title") or "").strip()
            url = (row.get("url") or "").strip()

            if not item_id:
                continue

            record = {
                "id": item_id,
                "title": title,
                "url": url,
                "action_raw": action_raw,
            }

            if action == DELETE_VALUE:
                deletes.append(record)
            elif action == ARCHIVE_VALUE:
                archives.append(record)
                # We also want to apply any title/url edits before archiving
                updates.append(record)
            else:
                # KEEP or anything else → treat as “keep, but apply edits”
                updates.append(record)

    return updates, deletes, archives


def ask_dry_run(num_updates, num_deletes, num_archives):
    """Ask the user whether to run in dry-run mode."""
    print("Planned changes based on CSV:")
    print(f" - Items to UPDATE (title/url): {num_updates}")
    print(f" - Items to ARCHIVE:           {num_archives}")
    print(f" - Items to DELETE:            {num_deletes}")
    while True:
        answer = input("Run in dry-run mode (no changes)? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'.")


def apply_updates(updates, dry_run: bool):
    """Apply title/url updates for rows not marked DELETE."""
    if not updates:
        print("✅ No items to update based on CSV.")
        return

    if dry_run:
        print("🛡️ DRY RUN: no updates will be performed.")
        print("The following items WOULD be updated (title/url):")
        for item in updates:
            print(f" - {item['id']}  |  title -> '{item['title']}'  |  url -> '{item['url']}'")
        return

    print("✏️ Applying title/url updates from CSV...")
    for item in tqdm(updates, desc="✏️ Updating", unit="item"):
        args = ["item", "edit", item["id"]]
        if item["title"]:
            args += ["--title", item["title"]]
        if item["url"]:
            # Assumes op CLI supports --url to set the primary URL
            args += ["--url", item["url"]]

        # Only call op if we actually have something to set
        if len(args) > 3:
            try:
                run_op(args)
            except Exception as e:
                print(f"⚠️ Failed to update {item['id']}: {e}")

    print("✅ Updates applied.")


def apply_archives(archives, dry_run: bool):
    """Archive items marked ARCHIVE in the CSV."""
    if not archives:
        print("✅ No items marked for archiving in the CSV.")
        return

    if dry_run:
        print("🛡️ DRY RUN: no items will be archived.")
        print("The following items WOULD be moved to Archive:")
        for item in archives:
            print(f" - {item['id']}  |  {item['title']}  |  {item['url']}")
        return

    print("📦 Archiving items marked as ARCHIVE in the CSV...")
    for item in tqdm(archives, desc="📦 Archiving", unit="item"):
        try:
            # Use --archive to move item to Archive instead of permanent delete
            run_op(["item", "delete", item["id"], "--archive"])
        except Exception as e:
            print(f"⚠️ Failed to archive {item['title']} ({item['id']}): {e}")

    print("✅ Archiving run complete.")


def apply_deletes(deletes, dry_run: bool):
    """Delete items marked DELETE in the CSV."""
    if not deletes:
        print("✅ No items marked for deletion in the CSV.")
        return

    if dry_run:
        print("🛡️ DRY RUN: no deletions will be performed.")
        print("The following items WOULD be deleted:")
        for item in deletes:
            print(f" - {item['id']}  |  {item['title']}  |  {item['url']}")
        return

    print("🗑️ Deleting items marked as DELETE in the CSV...")
    for item in tqdm(deletes, desc="🚮 Deleting", unit="item"):
        try:
            run_op(["item", "delete", item["id"]])
        except Exception as e:
            print(f"⚠️ Failed to delete {item['title']} ({item['id']}): {e}")

    print("✅ Deletion run complete.")


def main():
    print(f"🔐 Reading instructions from '{CSV_FILE}'…")
    try:
        updates, deletes, archives = load_from_csv(CSV_FILE)
        dry_run = ask_dry_run(len(updates), len(deletes), len(archives))

        # Order matters:
        # 1. Apply updates first (including for items that will be archived or deleted),
        #    so any manual CSV edits are reflected.
        # 2. Archive items.
        # 3. Delete items.
        apply_updates(updates, dry_run)
        apply_archives(archives, dry_run)
        apply_deletes(deletes, dry_run)

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
