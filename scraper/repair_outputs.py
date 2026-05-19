import argparse
import copy
import csv
import json
import logging
import os
import sys

from bs4 import BeautifulSoup

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config
from scraper.step_2_thread import crawl_thread, extract_inline_images
from scraper.step_3_download_attachments import download_attachments
from scraper.step_4_render import render_indices, render_thread_to_html
from scraper.utils import get_board_path


def iter_board_ids(selected_ids=None):
    if selected_ids:
        return [str(board_id) for board_id in selected_ids]

    board_ids = []
    for entry in sorted(os.listdir(config.OUTPUT_DIR)):
        if entry.isdigit() and os.path.isdir(os.path.join(config.OUTPUT_DIR, entry)):
            board_ids.append(entry)
    return board_ids


def load_latest_csv(board_path):
    csv_files = sorted([f for f in os.listdir(board_path) if f.endswith(".csv")], reverse=True)
    if not csv_files:
        return None, None, None

    csv_filename = csv_files[0]
    csv_path = os.path.join(board_path, csv_filename)
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    try:
        board_name = os.path.basename(csv_filename).split("_")[1]
    except IndexError:
        board_name = "unknown"

    return csv_path, board_name, rows


def normalize_post_inline_images(post, post_index):
    content = post.get("content") or ""
    attachments = list(post.get("attachments") or [])
    has_legacy_content = "data:image" in content
    has_legacy_attachments = any(
        att.get("type") == "base64" and att.get("data") for att in attachments
    )

    if not has_legacy_content and not has_legacy_attachments:
        return False

    modified = False
    extracted_attachments = []
    extracted_payloads = set()

    if has_legacy_content:
        wrapper_soup = BeautifulSoup(f"<div>{content}</div>", "html.parser")
        wrapper = wrapper_soup.div
        extracted_attachments = extract_inline_images(wrapper, post_index)
        if extracted_attachments:
            extracted_payloads = {att["data"] for att in extracted_attachments if att.get("data")}
            new_content = wrapper.decode_contents().strip()
            if new_content != content:
                post["content"] = new_content
                modified = True

    merged_attachments = []
    seen_keys = set()

    for attachment in extracted_attachments:
        key = (attachment.get("filename"), attachment.get("type"), attachment.get("url"))
        if key not in seen_keys:
            merged_attachments.append(attachment)
            seen_keys.add(key)

    for attachment in attachments:
        if (
            attachment.get("type") == "base64"
            and attachment.get("data")
            and attachment.get("data") in extracted_payloads
        ):
            modified = True
            continue

        key = (attachment.get("filename"), attachment.get("type"), attachment.get("url"))
        if key in seen_keys:
            continue

        merged_attachments.append(attachment)
        seen_keys.add(key)

    if merged_attachments != attachments:
        post["attachments"] = merged_attachments
        modified = True

    return modified


def normalize_thread_inline_images(thread_data, board_path, write=False):
    modified = False
    migrated_posts = 0

    for index, post in enumerate(thread_data.get("posts", []), start=1):
        if normalize_post_inline_images(post, index):
            modified = True
            migrated_posts += 1

    attachment_modified = False
    if write:
        attachment_modified = download_attachments(thread_data, board_path, "update")
    else:
        for post in thread_data.get("posts", []):
            if any(att.get("type") == "base64" and att.get("data") for att in post.get("attachments", [])):
                attachment_modified = True
                break

    if attachment_modified:
        modified = True

    return modified, migrated_posts


def save_thread_json(thread_data, json_path):
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(thread_data, f, ensure_ascii=False, indent=4)


def rebuild_board_html(board_id, board_name, board_rows, board_path):
    json_dir = os.path.join(board_path, config.JSON_DIR_NAME)

    for thread_meta in board_rows:
        json_path = os.path.join(json_dir, f"{thread_meta['id']}.json")
        if not os.path.exists(json_path):
            continue

        with open(json_path, "r", encoding="utf-8") as f:
            thread_data = json.load(f)

        html_filename = render_thread_to_html(copy.deepcopy(thread_data), board_path, board_name)
        thread_meta["html_filename"] = html_filename

    board_url = f"{config.BASE_URL}thread.php?bid={board_id}"
    render_indices(board_rows, board_path, board_name, board_url)


def repair_board(board_id, write=False, migrate_inline=True, repair_urls=True, rebuild_html=True):
    board_path = get_board_path(board_id)
    json_dir = os.path.join(board_path, config.JSON_DIR_NAME)
    csv_path, board_name, board_rows = load_latest_csv(board_path)

    result = {
        "board_id": board_id,
        "json_files": 0,
        "inline_threads_changed": 0,
        "inline_posts_changed": 0,
        "missing_json": 0,
        "url_mismatches": 0,
        "title_only_mismatches": 0,
        "recrawled_threads": 0,
        "changed": False,
    }

    if not os.path.isdir(json_dir):
        return result

    json_files = sorted([f for f in os.listdir(json_dir) if f.endswith(".json")])
    result["json_files"] = len(json_files)

    if migrate_inline:
        for json_filename in json_files:
            json_path = os.path.join(json_dir, json_filename)
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    thread_data = json.load(f)
            except Exception as exc:
                logging.warning(f"Failed to load {json_path}: {exc}")
                continue

            modified, migrated_posts = normalize_thread_inline_images(
                thread_data, board_path, write=write
            )
            if not modified:
                continue

            result["inline_threads_changed"] += 1
            result["inline_posts_changed"] += migrated_posts
            result["changed"] = True
            if write:
                save_thread_json(thread_data, json_path)

    if repair_urls and board_rows:
        for row in board_rows:
            row_id = row["id"]
            json_path = os.path.join(json_dir, f"{row_id}.json")

            if not os.path.exists(json_path):
                result["missing_json"] += 1
                needs_recrawl = True
                existing_json = None
            else:
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        existing_json = json.load(f)
                except Exception:
                    result["missing_json"] += 1
                    needs_recrawl = True
                    existing_json = None
                else:
                    if existing_json.get("url") != row.get("url"):
                        result["url_mismatches"] += 1
                        needs_recrawl = True
                    else:
                        needs_recrawl = False
                        if existing_json.get("title") != row.get("title"):
                            result["title_only_mismatches"] += 1

            if not needs_recrawl:
                continue

            result["changed"] = True
            result["recrawled_threads"] += 1
            if not write:
                continue

            thread_data = crawl_thread(row["url"], row_id)
            if not thread_data or not thread_data.get("posts"):
                logging.error(f"Failed to recrawl board {board_id} thread {row_id} from {row['url']}")
                continue

            attachment_modified = download_attachments(thread_data, board_path, "update")
            if attachment_modified:
                logging.info(f"Downloaded attachments while recrawling board {board_id} thread {row_id}")
            save_thread_json(thread_data, json_path)

    if write and rebuild_html and result["changed"] and board_rows:
        rebuild_board_html(board_id, board_name, board_rows, board_path)

    return result


def parse_board_ids(raw_board_ids):
    if not raw_board_ids:
        return None
    return [board_id.strip() for board_id in raw_board_ids.split(",") if board_id.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="Repair legacy inline images and JSON/CSV URL mismatches in scraped output."
    )
    parser.add_argument(
        "--board_ids",
        type=str,
        help="Comma-separated board IDs. Defaults to all boards under output/.",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Only report what would change.",
    )
    parser.add_argument(
        "--skip_inline_migration",
        action="store_true",
        help="Skip legacy base64 inline-image migration.",
    )
    parser.add_argument(
        "--skip_url_repair",
        action="store_true",
        help="Skip CSV/JSON URL mismatch repair.",
    )
    parser.add_argument(
        "--skip_html_rebuild",
        action="store_true",
        help="Skip board HTML rebuild after changes.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    write = not args.dry_run
    selected_board_ids = parse_board_ids(args.board_ids)
    results = []

    for board_id in iter_board_ids(selected_board_ids):
        result = repair_board(
            board_id=board_id,
            write=write,
            migrate_inline=not args.skip_inline_migration,
            repair_urls=not args.skip_url_repair,
            rebuild_html=not args.skip_html_rebuild,
        )
        results.append(result)

    print(
        "board json_files inline_threads_changed inline_posts_changed missing_json "
        "url_mismatches title_only_mismatches recrawled_threads changed"
    )
    for result in results:
        print(
            result["board_id"],
            result["json_files"],
            result["inline_threads_changed"],
            result["inline_posts_changed"],
            result["missing_json"],
            result["url_mismatches"],
            result["title_only_mismatches"],
            result["recrawled_threads"],
            int(result["changed"]),
        )


if __name__ == "__main__":
    main()
