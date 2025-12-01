# scraper/step_3_download_attachments.py
import argparse
from alive_progress import alive_bar
import base64
import json
import logging
import os
import sys

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config
from scraper.utils import get_board_path, sanitize_filename


def download_attachments(thread_data, board_path, run_mode):
    """Downloads attachments for a given thread."""
    if not thread_data or not thread_data.get('id'):
        return

    # Flatten the list of all attachments from all posts
    all_attachments = [att for post in thread_data.get('posts', []) for att in post.get('attachments', [])]

    if not all_attachments:
        return  # No attachments in this thread, so do nothing.

    # Create directory only if there are attachments
    attachment_dir = os.path.join(board_path, config.ATTACHMENT_DIR_NAME, thread_data['id'])
    os.makedirs(attachment_dir, exist_ok=True)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        ' AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'
    }

    for attachment in all_attachments:
        filename = sanitize_filename(attachment['filename'])
        filepath = os.path.join(attachment_dir, filename)

        if run_mode == 'update' and os.path.exists(filepath):
            logging.info("Attachment {filename} already exists. Skipping download in update mode.")
            continue

        try:
            if attachment['type'] == 'url':
                logging.info(f"Downloading attachment {attachment['url']} to {filepath}")
                response = requests.get(attachment['url'], headers=headers, timeout=60)
                response.raise_for_status()
                with open(filepath, 'wb') as f:
                    f.write(response.content)
            elif attachment['type'] == 'base64':
                logging.info(f"Saving base64 attachment to {filepath}")
                header, encoded = attachment['data'].split(',', 1)
                data = base64.b64decode(encoded)
                with open(filepath, 'wb') as f:
                    f.write(data)
        except Exception as e:
            logging.error(f"Failed to download attachment {attachment.get('url', 'N/A')}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Step 3: Download attachments from JSON files.")
    parser.add_argument("--board_id", type=int, default=config.BOARD_ID, help="The board ID.")
    parser.add_argument("--mode", type=str, default=config.RUN_MODE, choices=['overwrite', 'update'],
                        help="Run mode: 'overwrite' or 'update'.")
    args = parser.parse_args()

    logging.basicConfig(filename=f'output/{args.board_id}/step_3.log', filemode='w', encoding='utf-8',
                        level=logging.DEBUG, format='%(asctime)s %(levelname)s %(funcName)s(%(lineno)d) %(message)s')

    print("--- Running Step 3: Download Attachments ---")

    board_path = get_board_path(args.board_id)
    json_dir = os.path.join(board_path, config.JSON_DIR_NAME)

    if not os.path.isdir(json_dir):
        print(f"JSON directory not found at {json_dir}. Please run Step 2 first.")
        return 1

    json_files = [f for f in os.listdir(json_dir) if f.endswith('.json')]

    with alive_bar(len(json_files)) as bar:
        for i, json_filename in enumerate(json_files):
            logging.info(f"\n--- Processing file {i + 1}/{len(json_files)}: {json_filename} ---")
            json_filepath = os.path.join(json_dir, json_filename)

            with open(json_filepath, 'r', encoding='utf-8') as f:
                thread_data = json.load(f)

            download_attachments(thread_data, board_path, args.mode)

            bar()

    print("\nStep 3 finished!\n")


if __name__ == '__main__':
    sys.exit(main())
