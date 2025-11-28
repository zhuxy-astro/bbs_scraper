# scraper/utils.py
import os
import re
import requests
from bs4 import BeautifulSoup

# Assuming config is in the parent directory.
# This is a bit of a hack to make it work when running scripts from the root directory.
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config

def get_soup(url):
    """Fetches a URL and returns a BeautifulSoup object."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def get_board_path(board_id):
    """Constructs and creates the main output path for a board."""
    board_folder_name = str(board_id)
    path = os.path.join(config.OUTPUT_DIR, board_folder_name)
    os.makedirs(path, exist_ok=True)
    return path

def sanitize_filename(filename):
    """Removes invalid characters from a filename."""
    return re.sub(r'[\\/*?:"<>|]', "", filename)
