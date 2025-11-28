# scraper/step_4_render.py
import argparse
from alive_progress import alive_bar
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime
from urllib.parse import urljoin, unquote

from jinja2 import Environment, FileSystemLoader

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config
from scraper.utils import get_board_path, sanitize_filename


def _decode_link(match):
    """Decodes a 'jump-to.php' URL from a regex match."""
    url = match.group(1)
    return unquote(url)


def render_thread_to_html(thread_data, board_path, board_name):
    """Renders a single thread into an HTML file."""
    if not thread_data or not thread_data.get('id'):
        return None

    templates_dir = getattr(config, 'TEMPLATES_DIR', 'templates')
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template('thread.html')

    # Process attachments to add local path and image flag
    for post in thread_data.get('posts', []):
        if post.get('content'):
            # Replace escaped newlines with HTML line breaks
            post['content'] = post['content'].replace('\n', '<br>\n')

            # Find and replace jump-to.php links
            jump_to_pattern = r'href="jump-to\.php\?url=([^"]+)"'
            post['content'] = re.sub(jump_to_pattern, lambda m: f'href="{_decode_link(m)}"', post['content'])

        if post.get('attachments'):
            for att in post['attachments']:
                att['is_image'] = att['filename'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))

                # Check if the attachment file actually exists locally
                local_filepath = os.path.join(
                    board_path, config.ATTACHMENT_DIR_NAME, thread_data["id"], att["filename"])
                att['exists'] = os.path.exists(local_filepath)

                # Relative path from html/posts/xxx.html to attachments/thread_id/file
                att['local_path'] = f'../../{config.ATTACHMENT_DIR_NAME}/{thread_data["id"]}/{att["filename"]}'

    html_dir = os.path.join(board_path, config.HTML_DIR_NAME)
    posts_dir = os.path.join(html_dir, 'posts')
    os.makedirs(posts_dir, exist_ok=True)

    if thread_data.get('posts') and thread_data['posts'][0].get('post_time') != 'N/A':
        date = thread_data['posts'][0]['post_time'].split(' ')[0]
    else:
        date = 'nodate'
    sanitized_title = sanitize_filename(thread_data['title'])
    html_filename = f"{thread_data['id']}_{date}_{sanitized_title[:50]}.html"
    html_filepath = os.path.join(posts_dir, html_filename)

    logging.info(f"Rendering thread HTML to {html_filepath}")
    rendered_html = template.render(thread=thread_data, config=config, board_name=board_name)
    with open(html_filepath, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
    return html_filename


def render_indices(all_threads_metadata, board_path, board_name, board_url):
    """Renders the main index and per-year index HTML files for a board."""
    if not all_threads_metadata:
        print("No thread metadata to render indices.")
        return

    templates_dir = getattr(config, 'TEMPLATES_DIR', 'templates')
    env = Environment(loader=FileSystemLoader(templates_dir))
    html_dir = os.path.join(board_path, config.HTML_DIR_NAME)
    years_dir = os.path.join(html_dir, 'years')
    os.makedirs(years_dir, exist_ok=True)

    # Group threads by year
    threads_by_year = {}
    for thread_meta in all_threads_metadata:
        try:
            year = datetime.strptime(thread_meta['post_date'], '%Y-%m-%d').year
            if year not in threads_by_year:
                threads_by_year[year] = []
            threads_by_year[year].append(thread_meta)
        except (ValueError, TypeError):
            continue

    sorted_years = sorted(threads_by_year.keys(), reverse=True)

    # Render per-year index files
    year_template = env.get_template('index_year.html')
    for year in sorted_years:
        year_index_filepath = os.path.join(years_dir, f'index_{year}.html')
        print(f"Rendering year index HTML to {year_index_filepath}")

        # Sort threads within the year by last reply date
        threads_for_year = sorted(threads_by_year[year], key=lambda x: x['last_reply_date'], reverse=True)

        rendered_html = year_template.render(
            threads=threads_for_year,
            board_name=board_name,
            year=year
        )
        with open(year_index_filepath, 'w', encoding='utf-8') as f:
            f.write(rendered_html)

    # Render the main index file linking to the year files
    main_template = env.get_template('index_main.html')
    main_index_filepath = os.path.join(html_dir, 'index.html')
    update_date = datetime.now().strftime('%Y-%m-%d')
    print(f"Rendering main index HTML to {main_index_filepath}")
    rendered_main_html = main_template.render(
        board_name=board_name,
        years=sorted_years,
        board_url=board_url,
        update_date=update_date
    )
    with open(main_index_filepath, 'w', encoding='utf-8') as f:
        f.write(rendered_main_html)


def main():
    parser = argparse.ArgumentParser(description="Step 4: Render HTML files from JSON.")
    parser.add_argument("--board_id", type=int, default=config.BOARD_ID, help="The board ID.")
    args = parser.parse_args()

    logging.basicConfig(filename=f'output/{args.board_id}/step_4.log', filemode='w', encoding='utf-8',
                        level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    print("--- Running Step 4: Render HTML ---")

    board_path = get_board_path(args.board_id)
    json_dir = os.path.join(board_path, config.JSON_DIR_NAME)

    if not os.path.isdir(json_dir):
        print(f"JSON directory not found at {json_dir}. Please run Step 2 first.")
        return

    # We need the CSV to generate the index.html with all metadata
    csv_filepath = None
    try:
        csv_files = [f for f in os.listdir(board_path) if f.endswith('.csv')]
        if not csv_files:
            print(f"Error: No CSV file found in {board_path} to build the index. Please run Step 1 first.")
            return
        csv_filepath = os.path.join(board_path, sorted(csv_files, reverse=True)[0])
    except Exception as e:
        print(f"Error finding latest CSV file: {e}")
        return

    # Extract board name from CSV filename for the HTML title
    try:
        filename_parts = os.path.basename(csv_filepath).split('_')
        board_name = filename_parts[1]
    except IndexError:
        board_name = "unknown"

    with open(csv_filepath, 'r', encoding='utf-8') as f:
        full_thread_list = list(csv.DictReader(f))

    print(f"Found {len(full_thread_list)} threads in the CSV index.")

    with alive_bar(len(full_thread_list)) as bar:
        for i, thread_meta in enumerate(full_thread_list):
            logging.info(f"\n--- Rendering thread {i + 1}/{len(full_thread_list)}: {thread_meta['title']} ---")
            json_filepath = os.path.join(json_dir, f"{thread_meta['id']}.json")

            if not os.path.exists(json_filepath):
                logging.warrning(f"Warning: JSON file not found for thread {thread_meta['id']}. Skipping.")
                continue

            with open(json_filepath, 'r', encoding='utf-8') as f:
                thread_data = json.load(f)

            html_filename = render_thread_to_html(thread_data, board_path, board_name)

            # Add the generated html_filename to the dict so the index can use it
            thread_meta['html_filename'] = html_filename
            bar()

    board_url = urljoin(config.BASE_URL, f"thread.php?bid={args.board_id}")
    render_indices(full_thread_list, board_path, board_name, board_url)

    print("\nStep 4 finished!")


if __name__ == '__main__':
    main()
