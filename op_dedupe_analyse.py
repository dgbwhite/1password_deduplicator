import subprocess
import json
import csv
from collections import defaultdict
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import os
import time
import argparse
from datetime import datetime, timezone

# === CONFIGURATION ===
CSV_REPORT = "duplicate_report.csv"
REMOVE_DUPLICATES = False       # Set to True if you ever want this script to delete items
MAX_WORKERS = 8                 # Default parallel fetches; can be overridden via --workers
# ======================

TRANSIENT_PATTERNS = [
    "connection reset by peer",
    "tls handshake timeout",
    "eof",
    "temporary failure",
    "timeout awaiting response",
    # add more if you want them treated as transient, e.g.:
    # "broken pipe",
    # "bad record mac",
]


def is_transient_error(stderr: str) -> bool:
    """Return True if stderr from `op` looks like a transient network issue."""
    s = stderr.lower()
    return any(pat in s for pat in TRANSIENT_PATTERNS)


def run_op(args, retries: int = 3, base_delay: float = 1.0):
    """Run an op CLI command and return stdout as text, with limited retries."""
    cmd = ["op"] + args

    for attempt in range(1, retries + 1):
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            return result.stdout

        stderr = result.stderr.strip()
        # If it's the last attempt or not a transient error, fail fast
        if attempt == retries or not is_transient_error(stderr):
            raise RuntimeError(
                f"op {' '.join(args)} failed (attempt {attempt}/{retries}):\n{stderr}"
            )

        # Back off a bit before retrying
        delay = base_delay * attempt
        print(
            f"⏳ Transient error on {' '.join(args)} "
            f"(attempt {attempt}/{retries}), retrying in {delay:.1f}s…"
        )
        time.sleep(delay)


def normalise_url(url):
    """Normalise URLs for 'key' comparison.

    - force https
    - strip query and fragment
    - remove leading www.
    - collapse root '/' to empty
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    scheme = "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path or ""
    if path == "/":
        path = ""

    return f"{scheme}://{netloc}{path}"


def site_key_from_url(url):
    """Return a domain/site key (host with www. stripped)."""
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    return host or None


def extract_urls_from_item(item):
    """Extract all URLs from an item."""
    urls = set()

    legacy_url = item.get("url")
    if legacy_url:
        urls.add(legacy_url)

    for u in item.get("urls", []):
        if isinstance(u, dict):
            href = u.get("href")
            if href:
                urls.add(href)
        elif isinstance(u, str):
            urls.add(u)

    return urls


def extract_username_from_item(item):
    """Extract a username for the item.

    Priority:
    1. fields with purpose == 'USERNAME'
    2. fields with label in ('username', 'user name', 'login')
    3. top-level 'username' key if present

    Returns an empty string if no username is found.
    """
    # 1) Purpose-based (most robust in 1Password 8)
    for field in item.get("fields", []):
        purpose = (field.get("purpose") or "").upper()
        if purpose == "USERNAME":
            return (field.get("value") or "").strip()

    # 2) Label-based fallbacks
    for field in item.get("fields", []):
        label = (field.get("label") or "").strip().lower()
        if label in ("username", "user name", "login"):
            return (field.get("value") or "").strip()

    # 3) Top-level username if present
    if "username" in item:
        return (item.get("username") or "").strip()

    # 4) No username found
    return ""


def parse_timestamp(value):
    """Parse a timestamp from the item into epoch seconds."""
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0.0
        try:
            # Handle trailing Z as UTC
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0

    return 0.0


def get_best_timestamp(item):
    """Best timestamp: updated_at if available, else created_at."""
    updated_ts = parse_timestamp(item.get("updated_at"))
    created_ts = parse_timestamp(item.get("created_at"))
    return updated_ts or created_ts


def format_timestamp(ts):
    """Format epoch seconds as an ISO-like local datetime string."""
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(ts)
        return dt.isoformat(sep=" ", timespec="seconds")
    except Exception:
        return ""


def choose_vault():
    """Interactively prompt the user to select a vault, or use OP_VAULT."""
    env_vault = os.environ.get("OP_VAULT")
    if env_vault:
        print(f"🔐 Using vault from OP_VAULT: {env_vault}")
        return env_vault

    print("🔐 Fetching available vaults...")
    out = run_op(["vault", "list", "--format", "json"])
    vaults = json.loads(out)

    if not vaults:
        raise RuntimeError("No vaults found for this account.")

    print("\n📁 Available vaults...")
    for i, v in enumerate(vaults, start=1):
        print(f"  {i}. {v['name']}  (id: {v['id']})")

    while True:
        choice = input("\nSelect a vault by number (or press Enter for all vaults): ").strip()
        if choice == "":
            print("📦 No specific vault selected: scanning all vaults.")
            return None  # Means "all vaults"
        if not choice.isdigit():
            print("Please enter a number corresponding to a vault, or press Enter.")
            continue

        index = int(choice)
        if 1 <= index <= len(vaults):
            selected = vaults[index - 1]
            print(f"✅ Selected vault: {selected['name']} (id: {selected['id']})")
            return selected["id"]
        else:
            print("Invalid selection. Try again.")


def get_items(vault_id=None):
    """Return list of item IDs from 1Password."""
    args = ["item", "list", "--format", "json"]
    if vault_id:
        args.extend(["--vault", vault_id])

    out = run_op(args)
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
        for future in tqdm(as_completed(future_to_id), total=len(ids), desc="Fetching items"):
            item_id = future_to_id[future]
            try:
                item = future.result()
                items.append(item)
            except Exception as e:
                print(f"⚠️ Skipping item {item_id}: {e}")
    return items


def build_duplicate_index(items):
    """Build duplicate groups according to:

    1. same domain name AND username
    2. same key AND username

    - domain name: host part of any URL (www. stripped)
    - key: normalised full URL (scheme + host + path)
    """
    by_domain_and_username = defaultdict(list)
    by_key_and_username = defaultdict(list)

    for item in items:
        username = extract_username_from_item(item)
        username_key = username.strip().lower()

        urls = extract_urls_from_item(item)
        norm_urls = [normalise_url(u) for u in urls if u]

        # Rule 1: same domain name AND username
        domains = set()
        for u in urls:
            d = site_key_from_url(u)
            if d:
                domains.add(d)
        for domain in domains:
            by_domain_and_username[(domain, username_key)].append(item)

        # Rule 2: same key AND username (key = normalised URL)
        for nu in norm_urls:
            if nu:
                by_key_and_username[(nu, username_key)].append(item)

    return by_domain_and_username, by_key_and_username


def find_duplicates(by_domain_and_username, by_key_and_username):
    """Create duplicate groups based on the rules."""
    groups = []

    for key, items in by_domain_and_username.items():
        if len(items) > 1:
            groups.append({"reason": "domain+username", "key": key, "items": items})

    for key, items in by_key_and_username.items():
        if len(items) > 1:
            groups.append({"reason": "key+username", "key": key, "items": items})

    return groups


def choose_newest_item(items):
    """Return the newest item in a list based on best timestamp."""
    sorted_items = sorted(items, key=lambda i: get_best_timestamp(i), reverse=True)
    return sorted_items[0]


def summarise_item(item):
    """Return a compact summary for CSV/reporting."""
    title = item.get("title") or item.get("overview", {}).get("title") or ""
    vault = item.get("vault", {}).get("name") or ""
    url_set = extract_urls_from_item(item)
    urls = ", ".join(sorted(url_set)) if url_set else ""
    username = extract_username_from_item(item)
    last_ts = get_best_timestamp(item)
    last_updated = format_timestamp(last_ts)
    return title, vault, urls, username, last_updated


def write_report(groups):
    """Write duplicates report to CSV_REPORT.

    Rules:
    - For domain+username groups: keep_or_delete = 'review' for all items.
    - For key+username groups:
        newest  -> is_newer='YES', keep_or_delete='keep'
        others  -> is_newer='',     keep_or_delete='delete'
    """
    with open(CSV_REPORT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "group_id",
            "reason",
            "key",
            "keep_or_delete",
            "item_id",
            "title",
            "vault",
            "urls",
            "username",
            "last_updated",
            "is_newer",
        ])

        for idx, group in enumerate(groups, start=1):
            reason = group["reason"]
            key = group["key"]

            # Compute newest for this group for info / key+username decisions
            newest = choose_newest_item(group["items"])
            newest_id = newest["id"]

            for item in group["items"]:
                is_newer = "YES" if item["id"] == newest_id else ""

                if reason == "domain+username":
                    # Manual review only
                    keep_or_delete = "review"
                elif reason == "key+username":
                    # Auto suggestion: newest keep, others delete
                    keep_or_delete = "keep" if is_newer == "YES" else "delete"
                else:
                    # Shouldn't happen, but be defensive
                    keep_or_delete = "review"

                title, vault, urls, username, last_updated = summarise_item(item)
                writer.writerow([
                    idx,
                    reason,
                    repr(key),
                    keep_or_delete,
                    item["id"],
                    title,
                    vault,
                    urls,
                    username,
                    last_updated,
                    is_newer,
                ])

    print(f"📄 Duplicate report written to {CSV_REPORT}")


def delete_duplicates(groups):
    """Delete items according to the key+username rule only.

    - For key+username groups: delete items where keep_or_delete would be 'delete'
      (i.e. older items), keep the newest.
    - For domain+username groups: never delete automatically (manual review only).
    """
    for idx, group in enumerate(groups, start=1):
        reason = group["reason"]
        key = group["key"]

        print(f"\n🧹 Group {idx} ({reason} = {key})")

        if reason == "domain+username":
            print("   Skipping automatic deletion (manual review group).")
            for item in group["items"]:
                title, vault, urls, username, last_updated = summarise_item(item)
                print(f"   REVIEW: {item['id']} - {title} [{vault}] ({urls})")
            continue

        if reason == "key+username":
            newest = choose_newest_item(group["items"])
            newest_id = newest["id"]
            print(f"   Keeping newest: {newest_id} - {summarise_item(newest)[0]}")

            for item in group["items"]:
                if item["id"] == newest_id:
                    continue
                title, vault, urls, username, last_updated = summarise_item(item)
                print(f"   Deleting older: {item['id']} - {title} [{vault}] ({urls})")
                try:
                    run_op(["item", "delete", item["id"], "--yes"])
                except Exception as e:
                    print(f"   ⚠️ Failed to delete {item['id']}: {e}")
        else:
            print("   Unknown reason; no automatic deletion performed.")


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Find duplicate items in 1Password vaults.")
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help="Number of parallel workers to use when fetching items (default: %(default)s).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    global MAX_WORKERS

    args = parse_args(argv)
    if args.workers < 1:
        print("⚠️ --workers must be at least 1; defaulting to 1.")
        MAX_WORKERS = 1
    else:
        MAX_WORKERS = args.workers

    try:
        vault_id = choose_vault()
        print("\n📥 Fetching items...")
        ids = get_items(vault_id=vault_id)

        if not ids:
            print("No items found. Exiting.")
            return

        items = fetch_all_items_parallel(ids)

        print("🔍 Building duplicate index...")
        idx_domain, idx_key = build_duplicate_index(items)

        print("🧭 Finding potential duplicates...")
        dupes = find_duplicates(idx_domain, idx_key)

        if not dupes:
            print("✅ No duplicates found. Nice and tidy!")
            return

        write_report(dupes)

        if REMOVE_DUPLICATES:
            delete_duplicates(dupes)
        else:
            print("🛡️ Test mode: no items were deleted.")
            print(f"📄 Open '{CSV_REPORT}' to review 'review' rows and keep/delete suggestions.")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
