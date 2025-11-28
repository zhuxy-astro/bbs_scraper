# bbs_scraper/config.py

# The ID of the board you want to scrape.
# For example, for "蒙养山人类学学社(MANYATTA)", the URL is
# https://bbs.pku.edu.cn/v2/thread.php?bid=1090, so the BOARD_ID is 1090.
BOARD_ID = 1090  # 蒙养山人类学学社 for testing

# The run mode. Can be 'overwrite' or 'update'.
# 'overwrite': Scrapes everything from the beginning.
# 'update': Scrapes only the new or updated posts since the last run.
# RUN_MODE = "overwrite"
RUN_MODE = "update"

# Base URL for the BBS
BASE_URL = "https://bbs.pku.edu.cn/v2/"

# Output directory structure
OUTPUT_DIR = "output"
DATA_DIR_NAME = "data"
JSON_DIR_NAME = "jsons"

# Whether to download attachments. If set to False, attachment folders won't be created
# and the HTML will indicate that the files were not downloaded.
ATTACHMENT_DIR_NAME = "attachments"
HTML_DIR_NAME = "html"
TEMPLATES_DIR = "templates"
