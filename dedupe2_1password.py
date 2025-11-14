import subprocess
import json
import csv
from collections import defaultdict
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# === CONFIGURATION ===
VAULT_NAME = "David's"          # Change if needed
CSV_REPORT = "duplicate_report.csv"
REMOVE_DUPLICATES = False       # Set to True to allow deletions
MAX_WORKERS = 8                 # Parallel fetches
# ======================

def run_op(args):
    """Run an op CLI command and return stdout as text or raise on error."""
    result = subprocess.run(["op"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"op {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout

def get_item_ids(vault_name):
    """Return list of item IDs from the given vault."""
    out = run_op(["item", "list", "--vault", vault_name, "--format", "json"])
    items = json.loads(out)
    return [item["id"] for item in items]

def fetch_one_item(item_id):
    """Fetch a single item JSON by ID."""
    data = run_op(["item", "get", item_id, "--format", "json"])
    return json.loads(data)

def fetch_all_items_parallel(ids):
    """Fetch all items in parallel, with a progress bar."""
    items = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_id = {executor.submit(fetch_one_item, item_id): item_id for item_id in ids}
        for future in tqdm(as_completed(future_to_id),
                           total=len(future_to_id),
                           desc="📥 Fetching items",
                           unit="item"):
            item_id = future_to_id[future]
            try:
                item = future.result()
                items.append(item)
            except Exception as e:
                print(f"⚠️ Skipping item {item_id}: {e}")
    return items

def normalize_url(href):
    """
    Normalise a URL so that logically identical URLs group together.
    - Lowercase scheme and host
    - Strip trailing slash from path
    - Ignore query/fragment for dedupe purposes
    """
    try:
        parsed = urlparse(href)
        scheme = (parsed.scheme or "https").lower()
        netloc = parsed.netloc.lower()
        path = (parsed.path or "").rstrip("/")
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return href or ""

def get_domain(href):
    try:
        return urlparse(href).netloc.lower()
    except Exception:
        return ""

def is_localhost_domain(domain):
    if not domain:
        return False
    if domain in {"localhost", "127.0.0.1"}:
        return True
    if domain.endswith(".local"):
        return True
    return False

def get_best_timestamp(item):
    """
    Prefer updatedAt / updated_at, then createdAt / created_at.
    Returns an ISO-like string or "".
    """
    return (
        item.get("updatedAt")
        or item.get("updated_at")
        or item.get("createdAt")
        or item.get("created_at")
        or ""
    )

def identify_duplicates(items):
    """
    Group items to find duplicates.

    Rules:
    - For normal sites: key = (normalized_full_url, username)
    - For localhost / 127.0.0.1 / *.local: key = ("local", username, normalized_title)
    """
    grouped = defaultdict(list)

    for item in items:
        urls = item.get("urls", [])
        fields = item.get("fields", [])
        updated = get_best_timestamp(item)
        title = item.get("title", "") or ""
        item_id = item.get("id")

        # Find username field
        username = None
        for f in fields:
            if f.get("id") == "username":
                username = f.get("value")
                break

        if not username:
            continue

        href = urls[0].get("href", "") if urls else ""
        domain = get_domain(href)

        if is_localhost_domain(domain):
            # Local app-style entries: use title + username as key
            key = ("local", username.strip().lower(), title.strip().lower())
            normalized_href = href  # keep original for reporting only
        else:
            if not href:
                # No URL and not localhost: skip for our purposes
                continue
            normalized_href = normalize_url(href)
            key = (normalized_href, username.strip().lower())

        grouped[key].append({
            "id": item_id,
            "title": title,
            "updated": updated,
            "url": normalized_href,
            "domain": domain,
            "username": username,
        })

    # Only keep keys with more than one item (actual duplicates)
    return {k: v for k, v in grouped.items() if len(v) > 1}

def write_report(dupes):
    print(f"📝 Writing CSV report to: {CSV_REPORT}")
    with open(CSV_REPORT, mode="w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "key_type",
                "url_or_title_key",
                "username",
                "item_id",
                "title",
                "url",
                "updatedAt",
                "is_newest",
                "action",
            ],
        )
        writer.writeheader()

        for key, group in dupes.items():
            # Decode key for reporting
            if key[0] == "local":
                key_type = "local_app"
                _, uname_key, title_key = key
                url_or_title_key = title_key
                key_username = uname_key
            else:
                key_type = "full_url"
                url_key, uname_key = key
                url_or_title_key = url_key
                key_username = uname_key

            # Newest first (ISO timestamps sort lexicographically fine)
            sorted_group = sorted(group, key=lambda x: x["updated"], reverse=True)
            for i, item in enumerate(sorted_group):
                is_newest = "YES" if i == 0 else "NO"
                action = "KEEP" if i == 0 else "DELETE"
                writer.writerow({
                    "key_type": key_type,
                    "url_or_title_key": url_or_title_key,
                    "username": key_username,
                    "item_id": item["id"],
                    "title": item["title"],
                    "url": item["url"],
                    "updatedAt": item["updated"],
                    "is_newest": is_newest,
                    "action": action,
                })

def delete_duplicates(dupes):
    print("🗑️ Deleting older duplicates...")
    groups = list(dupes.values())
    for group in tqdm(groups, desc="🚮 Deleting", unit="group"):
        sorted_group = sorted(group, key=lambda x: x["updated"], reverse=True)
        to_delete = sorted_group[1:]  # keep newest
        for item in to_delete:
            try:
                run_op(["item", "delete", item["id"]])
            except Exception as e:
                print(f"⚠️ Failed to delete {item['title']} ({item['id']}): {e}")

def main():
    print("🔐 Starting 1Password duplicate scan…")
    try:
        ids = get_item_ids(VAULT_NAME)
        print(f"🔎 Found {len(ids)} items in vault '{VAULT_NAME}'.")
        items = fetch_all_items_parallel(ids)

        dupes = identify_duplicates(items)
        if not dupes:
            print("✅ No duplicates found.")
            return

        write_report(dupes)

        if REMOVE_DUPLICATES:
            delete_duplicates(dupes)
            print("✅ Deletion complete.")
        else:
            print("🛡️ Test mode: no items were deleted.")
            print(f"📄 Open '{CSV_REPORT}' to review what would be deleted.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()