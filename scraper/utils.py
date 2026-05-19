# scraper/utils.py
import hashlib
import http.cookiejar
import os
import re
import requests
from bs4 import BeautifulSoup

# Assuming config is in the parent directory.
# This is a bit of a hack to make it work when running scripts from the root directory.
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'
}

_session = None
_logged_in = False


def _load_dotenv(path=".env"):
    """Loads simple KEY=VALUE pairs into os.environ if not already set."""
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _is_login_page(response):
    return (
        response.url.endswith("/login.php")
        or 'id="page-login"' in response.text
        or 'data-action="login"' in response.text
    )


def _get_global_time(html):
    match = re.search(r'id="global-time">\s*(\d+)\s*<', html)
    if not match:
        raise RuntimeError("Could not find BBS global-time on login page.")
    return match.group(1)


def get_session():
    """Returns a shared requests session with persisted BBS cookies."""
    global _session

    if _session is not None:
        return _session

    session = requests.Session()
    session.headers.update(HEADERS)
    cookie_file = getattr(config, "BBS_COOKIE_FILE", ".bbs_cookies")
    session.cookies = http.cookiejar.MozillaCookieJar(cookie_file)
    if os.path.exists(cookie_file):
        try:
            session.cookies.load(ignore_discard=True, ignore_expires=True)
        except http.cookiejar.LoadError:
            pass

    _session = session
    return _session


def reset_session(clear_login=False):
    """Drops the shared session so the next fetch starts fresh."""
    global _session, _logged_in
    _session = None
    if clear_login:
        _logged_in = False


def login(force=False):
    """Logs in to BBS with credentials from environment or .env."""
    global _logged_in

    _load_dotenv()
    username = os.environ.get("BBS_USERNAME")
    password = os.environ.get("BBS_PASSWORD")
    keepalive = os.environ.get("BBS_KEEPALIVE", "1")

    if not username or not password:
        raise RuntimeError("BBS_USERNAME and BBS_PASSWORD must be set in environment or .env.")

    if _logged_in and not force:
        return True

    session = get_session()
    login_page = session.get(config.BBS_LOGIN_URL, timeout=30)
    login_page.raise_for_status()
    global_time = _get_global_time(login_page.text)
    token = hashlib.md5(f"{password}{username}{global_time}{password}".encode("utf-8")).hexdigest()

    response = session.post(
        config.BBS_LOGIN_API_URL,
        data={
            "username": username,
            "password": password,
            "keepalive": 1 if str(keepalive).lower() in {"1", "true", "yes"} else 0,
            "time": global_time,
            "t": token,
        },
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("success"):
        raise RuntimeError(f"BBS login failed with error code {result.get('error')}.")

    _logged_in = True
    cookie_file = getattr(config, "BBS_COOKIE_FILE", ".bbs_cookies")
    try:
        session.cookies.save(cookie_file, ignore_discard=True, ignore_expires=True)
    except Exception:
        pass
    return True


def fetch(url, timeout=30, require_login=True, **kwargs):
    """Fetches a URL, logging in and retrying once if BBS redirects to login."""
    session = get_session()
    response = session.get(url, timeout=timeout, **kwargs)
    if require_login and _is_login_page(response):
        login(force=True)
        response = session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response


def get_soup(url, timeout=30):
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        response = fetch(url, timeout=timeout)
        return BeautifulSoup(response.text, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None
    except RuntimeError as e:
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
