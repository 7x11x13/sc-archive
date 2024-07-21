# sc-archive

Tool I use to archive and keep track of songs from people I follow on SoundCloud. Requires a running [cookie relay server](https://github.com/7x11x13/cookie-relay)

## Setup

0. Clone this repo
1. Create file `.secret/config.ini` (see `sc_archive/example.ini` for an example)
2. Create file `.env` with line `ARCHIVE_PATH=<path where you want to download tracks to>`
3. Run `sudo docker compose up`