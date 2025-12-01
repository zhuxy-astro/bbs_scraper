# scraper/step_1_index.py
import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config
from scraper.utils import get_soup, get_board_path


def normalize_date(date_str):
    """Converts relative BBS date strings to 'YYYY-MM-DD' format."""
    today = datetime.now()

    try:
        # Format: "30分钟前" -> Today or Yesterday
        if "分钟前" in date_str:
            try:
                minutes_ago = int(re.search(r"\d+", date_str).group())
                event_time = datetime.now() - timedelta(minutes=minutes_ago)
                return event_time.strftime("%Y-%m-%d")
            except (ValueError, AttributeError):
                pass  # Fall through if parsing fails

        # Format: "11:57" -> Today
        if ":" in date_str and "-" not in date_str and "天" not in date_str:
            return today.strftime("%Y-%m-%d")

        # Format: "昨天 23:39"
        if "昨天" in date_str:
            yesterday = today - timedelta(days=1)
            return yesterday.strftime("%Y-%m-%d")

        # Format: "前天 23:39"
        if "前天" in date_str:
            day_before = today - timedelta(days=2)
            return day_before.strftime("%Y-%m-%d")

        # Format: "11-04 13:14" or "11-04" -> This year
        if "-" in date_str and len(date_str.split("-")) == 2:
            date_part = date_str.split(" ")[0]
            return f"{today.year}-{date_part}"

        # Format: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        if "-" in date_str and len(date_str.split("-")) == 3:
            return date_str.split(" ")[0]
    except Exception:
        # Fallback to original string if any error occurs
        return date_str

    return date_str


def get_board_name(soup):
    """Extracts the board name from the index page soup."""
    try:
        eng_name_span = soup.select_one("div#title span.title-text.eng")
        if eng_name_span and eng_name_span.text.strip():
            return eng_name_span.text.strip()

        board_link = soup.select_one("div.breadcrumb-trail a[href^='board.php?bid=']")
        if board_link:
            return board_link.text.strip()
    except Exception as e:
        print(f"Error getting board name: {e}")
    return "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="Step 1: Crawl a BBS board index and save thread metadata to a CSV."
    )
    parser.add_argument(
        "--board_id",
        type=int,
        default=config.BOARD_ID,
        help="The ID of the board to scrape.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default=config.RUN_MODE,
        choices=["overwrite", "update"],
        help="Run mode: 'overwrite' or 'update'.",
    )
    args = parser.parse_args()

    print(f"--- Running Step 1: Crawl Board Index for board {args.board_id} ---")

    # Initial page fetch just to get board name
    initial_url = urljoin(
        config.BASE_URL, f"thread.php?bid={args.board_id}&mode=topic&page=1"
    )
    soup = get_soup(initial_url)
    if not soup:
        print(f"Failed to fetch initial page for board {args.board_id}. Exiting.")
        return 1

    board_name = get_board_name(soup)
    if board_name == "unknown":
        print("\nError: Could not determine board name. This may be due to:")
        print("1. Network issues (e.g., requires PKU campus network or VPN).")
        print("2. The board requiring login (not currently supported).")
        print("3. The board URL being invalid.")
        print(
            "Please check your network settings and the board ID in config.py, then try again."
        )
        return 1

    board_path = get_board_path(args.board_id)
    print(f"Scraping board: {board_name} (ID: {args.board_id})")

    # --- Merged Crawl and Save Logic ---

    existing_csv_file = None
    last_update_time = None
    if args.mode == "update":
        try:
            csv_files = [f for f in os.listdir(board_path) if f.endswith(".csv")]
            if csv_files:
                existing_csv_file = os.path.join(
                    board_path, sorted(csv_files, reverse=True)[0]
                )
                with open(existing_csv_file, "r", encoding="utf-8") as f:
                    last_update_str = next(csv.DictReader(f))["last_reply_date"]
                print(f"Update mode: Last update date found is {last_update_str}")
                if " " in last_update_str:
                    last_update_time = datetime.strptime(
                        last_update_str, "%Y-%m-%d %H:%M:%S"
                    )
                else:
                    last_update_time = datetime.strptime(last_update_str, "%Y-%m-%d")
        except Exception as e:
            print(
                f"Could not determine last update date: {e}. Defaulting to overwrite."
            )
            args.mode = "overwrite"

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    new_csv_filename = f"{args.board_id}_{board_name}_{timestamp}.csv"
    new_csv_filepath = os.path.join(board_path, new_csv_filename)

    fieldnames = [
        "id",
        "title",
        "author",
        "post_date",
        "replies",
        "last_reply_date",
        "last_reply_author",
        "url",
    ]
    newly_crawled_threads = {}

    with open(new_csv_filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        page_num = 1
        stop_crawling = False
        while True:
            index_url = urljoin(
                config.BASE_URL,
                f"thread.php?bid={args.board_id}&mode=topic&page={page_num}",
            )
            print(f"Crawling index page: {index_url}")

            # Re-use soup for first page
            page_soup = soup if page_num == 1 else get_soup(index_url)

            if not page_soup or page_soup.find("div", class_="error-page"):
                print("Could not fetch page or error page found.")
                break

            list_items = page_soup.select("div.list-item-topic")
            if not list_items:
                print("No more list items found.")
                break

            page_threads_found = 0
            for item in list_items:
                try:
                    authors = item.select("div.author")
                    if not authors:
                        continue

                    last_reply_div = authors[1] if len(authors) > 1 else authors[0]

                    # Normalize dates
                    raw_post_date = authors[0].select_one(".time").text.strip()
                    post_date = normalize_date(raw_post_date)
                    raw_last_reply_date = last_reply_div.select_one(
                        ".time"
                    ).text.strip()
                    last_reply_date = normalize_date(raw_last_reply_date)

                    if args.mode == "update" and last_update_time:
                        current_reply_dt = datetime.strptime(
                            last_reply_date, "%Y-%m-%d"
                        )
                        if (
                            current_reply_dt.date() < last_update_time.date()
                        ):  # Changed from <= to <
                            stop_crawling = True
                            break

                    title_link = item.find("a", class_="link", href=True)
                    id_div = item.select_one("div.id.l")
                    if not id_div or not id_div.text.strip().isdigit():
                        continue
                    thread_id = id_div.text.strip()

                    thread_info = {
                        "id": thread_id,
                        "url": urljoin(config.BASE_URL, title_link["href"]),
                        "title": item.select_one("div.title").text.strip(),
                        "author": authors[0].select_one(".name").text.strip(),
                        "post_date": post_date,
                        "replies": (
                            item.select_one("div.reply-num").text.strip()
                            if item.select_one("div.reply-num")
                            else "0"
                        ),
                        "last_reply_author": last_reply_div.select_one(
                            ".name"
                        ).text.strip(),
                        "last_reply_date": last_reply_date,
                    }

                    if thread_id not in newly_crawled_threads:
                        writer.writerow(thread_info)
                        newly_crawled_threads[thread_id] = thread_info
                        page_threads_found += 1

                except Exception as e:
                    print(f"Error parsing a thread item on page {page_num}: {e}")
                    continue

            print(
                f"Found and wrote {page_threads_found} new threads from page {page_num}."
            )
            if stop_crawling:
                print("Reached last update date. Stopping crawl.")
                break

            next_page_div = page_soup.select_one(
                'div.paging-button:-soup-contains("下一页")'
            )
            if not (next_page_div and next_page_div.find("a")):
                print("Last page reached.")
                break

            page_num += 1
            time.sleep(1)

    # In update mode, merge old data
    if args.mode == "update" and existing_csv_file:
        print(f"Merging with old data from {existing_csv_file}")
        with open(existing_csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["id"] not in newly_crawled_threads:
                    newly_crawled_threads[row["id"]] = row

        all_threads = sorted(
            newly_crawled_threads.values(),
            key=lambda x: x["last_reply_date"],
            reverse=True,
        )

        with open(new_csv_filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_threads)

        os.remove(existing_csv_file)

    print(f"\nStep 1 finished successfully. Final CSV saved to: {new_csv_filepath}\n")


if __name__ == "__main__":
    sys.exit(main())
