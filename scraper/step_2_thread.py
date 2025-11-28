# scraper/step_2_thread.py
import argparse
from alive_progress import alive_bar
import csv
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

from bs4 import Tag

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config
from scraper.utils import get_soup, get_board_path, sanitize_filename


def parse_post(post_element, base_url):
    """Parses a single post element and returns a dictionary of its data."""
    post_data = {"post_time": "N/A", "edit_time": "N/A"}
    try:
        author_link = post_element.select_one("p.username a")
        post_data["author"] = author_link.text.strip() if author_link else "N/A"

        time_container = post_element.select_one("div.sl-triangle-container")
        if time_container:
            main_time_span = time_container.select_one("span.title span")
            if main_time_span and "修改" in main_time_span.text:
                edit_time_match = re.search(
                    r"(\d{4}-\d{1,2}-\d{1,2}\s\d{2}:\d{2}:\d{2})", main_time_span.text
                )
                if edit_time_match:
                    post_data["edit_time"] = edit_time_match.group(1)

            original_time_span = time_container.select_one("ul.down-list li span")
            if original_time_span:
                original_time_match = re.search(
                    r"(\d{4}-\d{1,2}-\d{1,2}\s\d{2}:\d{2}:\d{2})",
                    original_time_span.text,
                )
                if original_time_match:
                    post_data["post_time"] = original_time_match.group(1)

            if (
                post_data["post_time"] == "N/A"
                and main_time_span
                and "发表" in main_time_span.text
            ):
                post_time_match = re.search(
                    r"(\d{4}-\d{1,2}-\d{1,2}\s\d{2}:\d{2}:\d{2})", main_time_span.text
                )
                if post_time_match:
                    post_data["post_time"] = post_time_match.group(1)

        floor_element = post_element.select_one("span.post-id")
        post_data["floor"] = floor_element.text.strip() if floor_element else ""

        content_element = post_element.select_one("div.content div.body")
        if not content_element:
            return None

        quotes = []
        body_content_parts = []
        all_children = list(content_element.children)
        i = 0
        while i < len(all_children):
            child = all_children[i]

            # Check if the child is a tag and a quotehead
            if (
                isinstance(child, Tag)
                and child.name == "p"
                and "quotehead" in child.get("class", [])
            ):
                quoted_user_match = re.search(r'data-username="([^"]+)"', str(child))
                user = quoted_user_match.group(1) if quoted_user_match else ""

                quote_text_parts = []
                i += 1  # Move past the quotehead
                while i < len(all_children):
                    node = all_children[i]
                    if (
                        isinstance(node, Tag)
                        and node.name == "p"
                        and "blockquote" in node.get("class", [])
                    ):
                        quote_text_parts.append(node.get_text(strip=True))
                        i += 1
                    elif (
                        isinstance(node, str) and not node.strip()
                    ):  # It's just whitespace
                        i += 1
                    else:
                        break  # No more blockquotes for this quote

                if quote_text_parts:
                    quotes.append({"user": user, "text": " ".join(quote_text_parts)})
            else:
                # Not a quote, so it's regular content
                body_content_parts.append(str(child))
                i += 1

        post_data["quotes"] = quotes
        post_data["content"] = "".join(body_content_parts).strip()

        # Attachment logic
        attachments = []
        for img in post_element.select("div.content div.body img"):
            img_src = img.get("src")
            if not img_src:
                continue
            if "attach" in img_src:
                attachments.append(
                    {
                        "type": "url",
                        "url": urljoin(base_url, img_src),
                        "filename": os.path.basename(urlparse(img_src).path),
                    }
                )
            elif img_src.startswith("data:image"):
                try:
                    file_ext = re.search(r"data:image/(\w+);", img_src).group(1)
                    filename = f"inline_{int(time.time() * 1000)}.{file_ext}"
                    attachments.append(
                        {"type": "base64", "data": img_src, "filename": filename}
                    )
                except Exception as e:
                    logging.warning(f"Could not parse base64 image data: {e}")

        attachment_div = post_element.select_one("div.attachment")
        if attachment_div:
            for attach_link in attachment_div.select("li a"):
                if "highslide" in attach_link.get("class", []):
                    continue
                attach_url = attach_link.get("href")
                if attach_url:
                    attachments.append(
                        {
                            "type": "url",
                            "url": urljoin(base_url, attach_url),
                            "filename": attach_link.text.strip(),
                        }
                    )
        post_data["attachments"] = attachments

    except Exception as e:
        import traceback

        logging.error(f"Error parsing post: {e}\n{traceback.format_exc()}")
        return None
    return post_data


def crawl_thread(thread_url, thread_id):
    """Crawls a single thread, handling multiple pages by constructing page URLs."""
    thread_data = {"posts": []}

    # --- First page ---
    logging.info(f"Crawling thread page 1: {thread_url}")
    soup = get_soup(thread_url)
    if not soup:
        return None

    # Parse title etc. on first page
    if not thread_data.get("title"):
        title_element = soup.select_one("header h3")
        thread_data["title"] = (
            title_element.text.strip() if title_element else "Untitled"
        )
        thread_data["id"] = thread_id
        thread_data["url"] = thread_url

    # Parse posts on first page
    for post_element in soup.select("div.post-card"):
        post_content = parse_post(post_element, config.BASE_URL)
        if post_content:
            thread_data["posts"].append(post_content)

    # Determine total number of pages
    total_pages = 1
    if paging_div := soup.select_one("div.paging"):
        total_pages_elem = paging_div.find(string=re.compile(r"/\s*\d+"))
        if total_pages_elem:
            try:
                total_pages = int(total_pages_elem.strip().replace("/", "").strip())
            except (ValueError, AttributeError):
                pass

    if total_pages <= 1:
        return thread_data

    # --- Subsequent pages ---
    parts = urlparse(thread_url)
    query_dict = parse_qs(parts.query)

    for page_num in range(2, total_pages + 1):
        query_dict["page"] = [str(page_num)]
        new_query = urlencode(query_dict, doseq=True)
        next_page_url = parts._replace(query=new_query).geturl()

        logging.info(f"Crawling thread page {page_num}/{total_pages}: {next_page_url}")
        page_soup = get_soup(next_page_url)
        if not page_soup:
            logging.warning(f"Warning: Failed to fetch page {page_num}. Skipping.")
            continue

        for post_element in page_soup.select("div.post-card"):
            post_content = parse_post(post_element, config.BASE_URL)
            if post_content:
                thread_data["posts"].append(post_content)

        time.sleep(1)

    return thread_data


def save_thread_to_json(thread_data, board_path):
    """Saves the crawled thread data to a JSON file."""
    if not thread_data or not thread_data.get("id"):
        return None
    json_dir = os.path.join(board_path, config.JSON_DIR_NAME)
    os.makedirs(json_dir, exist_ok=True)
    json_filepath = os.path.join(json_dir, f"{thread_data['id']}.json")
    logging.info(f"Saving thread to {json_filepath}")
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(thread_data, f, ensure_ascii=False, indent=4)
    return json_filepath


def main():
    parser = argparse.ArgumentParser(
        description="Step 2: Crawl threads from a CSV file and save them as JSON files."
    )
    parser.add_argument(
        "--csv_file",
        type=str,
        help="Path to the CSV file containing thread metadata. If not provided, finds the latest.",
    )
    parser.add_argument(
        "--board_id",
        type=int,
        default=config.BOARD_ID,
        help="The board ID, used to find the latest CSV if --csv_file is not provided.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default=config.RUN_MODE,
        choices=["overwrite", "update"],
        help="Run mode: 'overwrite' or 'update'.",
    )
    args = parser.parse_args()

    logging.basicConfig(filename=f'output/{args.board_id}/step_2.log', filemode='w', encoding='utf-8',
                        level=logging.DEBUG, format='%(asctime)s %(levelname)s %(funcName)s(%(lineno)d) %(message)s')

    print("--- Running Step 2: Crawl Individual Threads ---")

    board_path = get_board_path(args.board_id)
    csv_filepath = args.csv_file

    if not csv_filepath:
        try:
            csv_files = [f for f in os.listdir(board_path) if f.endswith(".csv")]
            if not csv_files:
                print(
                    f"Error: No CSV file found in {board_path}. Please run Step 1 first."
                )
                return
            csv_filepath = os.path.join(board_path, sorted(csv_files, reverse=True)[0])
            print(f"Found latest CSV: {csv_filepath}")
        except Exception as e:
            print(f"Error finding latest CSV file: {e}")
            return

    if not os.path.exists(csv_filepath):
        print(f"Error: CSV file not found at {csv_filepath}")
        return

    with open(csv_filepath, "r", encoding="utf-8") as f:
        all_threads = list(csv.DictReader(f))

    # --- New Summary, Retry, and Smart Update Logic ---

    threads_to_process = []
    skipped_count = 0
    json_dir = os.path.join(board_path, config.JSON_DIR_NAME)
    os.makedirs(json_dir, exist_ok=True)

    # Smart filtering for update mode
    for thread_meta in all_threads:
        json_filepath = os.path.join(json_dir, f"{thread_meta['id']}.json")
        if os.path.exists(json_filepath) and args.mode == "update":
            try:
                with open(json_filepath, "r", encoding="utf-8") as f:
                    existing_json = json.load(f)

                replies_in_csv = int(thread_meta["replies"])
                replies_in_json = len(existing_json.get("posts", [])) - 1

                last_reply_date_csv = datetime.strptime(
                    thread_meta["last_reply_date"], "%Y-%m-%d"
                )

                latest_date_in_json = datetime.min
                for post in existing_json.get("posts", []):
                    if post.get("post_time") and post["post_time"] != "N/A":
                        post_time = datetime.strptime(
                            post["post_time"], "%Y-%m-%d %H:%M:%S"
                        )
                        if post_time > latest_date_in_json:
                            latest_date_in_json = post_time

                if (
                    replies_in_csv <= replies_in_json
                    and last_reply_date_csv.date() >= latest_date_in_json.date()
                ):
                    skipped_count += 1
                    continue
            except (json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
                logging.warning(
                    f"Warning: Could not validate existing JSON for thread {thread_meta['id']}. Re-crawling. Error: {e}"
                )

        threads_to_process.append(thread_meta)

    total_in_csv = len(all_threads)
    total_to_crawl = len(threads_to_process)
    max_retries = 3

    for attempt in range(max_retries):
        if not threads_to_process:
            break

        print(
            f"\n--- Running crawl attempt {attempt + 1}/{max_retries} for {len(threads_to_process)} threads ---"
        )

        currently_failed_threads = []

        with alive_bar(len(all_threads)) as bar:
            for i, thread_meta in enumerate(threads_to_process):
                logging.info(
                    f"\n--- Processing thread {i + 1}/{len(threads_to_process)}: {thread_meta['title']} ---"
                )

                thread_data = crawl_thread(thread_meta["url"], thread_meta["id"])

                if not thread_data or not thread_data["posts"]:
                    logging.error(f"Failed to crawl thread {thread_meta['id']}.")
                    currently_failed_threads.append(thread_meta)
                else:
                    save_thread_to_json(thread_data, board_path)

                bar()

        threads_to_process = currently_failed_threads

        if threads_to_process:
            print(
                f"\n--- {len(threads_to_process)} threads failed. Retrying in 5 seconds... ---"
            )
            time.sleep(5)

    final_failed_threads = threads_to_process
    success_count = total_to_crawl - len(final_failed_threads)
    final_failed_ids = [meta["id"] for meta in final_failed_threads]

    print("\n" + "=" * 25)
    print("--- Crawl Summary ---")
    print(f"Total threads in CSV:   {total_in_csv}")
    print(f"Already existed:        {skipped_count}")
    print(f"Attempted to crawl:     {total_to_crawl}")
    print(f"Successfully crawled:   {success_count}")
    print(f"Failed to crawl:          {len(final_failed_ids)}")
    if final_failed_ids:
        print(f"Failed thread IDs: {', '.join(final_failed_ids)}")
    print("=" * 25)
    print("\nStep 2 finished.\n")


if __name__ == "__main__":
    main()
