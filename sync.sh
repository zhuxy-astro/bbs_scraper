#!/bin/bash

LOCAL_PATH="$HOME/Projects/bbs_scraper"
BOARD_ID="$1"
MODE="update"

cd "$LOCAL_PATH" || exit 1
./venv/bin/python3 -m scraper.step_1_index --board_id "$BOARD_ID" --mode $MODE || exit 1
./venv/bin/python3 -m scraper.step_2_thread --board_id "$BOARD_ID" --mode $MODE || exit 1
./venv/bin/python3 -m scraper.step_3_download_attachments --board_id "$BOARD_ID" --mode $MODE || exit 1
./venv/bin/python3 -m scraper.step_4_render --board_id "$BOARD_ID" || exit 1

rsync -az --stats --delete --exclude='venv/' --exclude='**/.DS_Store' ./ ali:~/bbs_scraper/
