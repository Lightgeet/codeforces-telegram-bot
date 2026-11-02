# Codeforces Telegram Contest Notification Bot

A Telegram bot that watches upcoming Codeforces contests and sends users notifications for the divisions they choose.

## Table of contents

- [Overview](#overview)
- [Features](#features)
- [Available commands](#available-commands)
- [How it works](#how-it-works)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Installation and setup](#installation-and-setup)
- [Environment variables](#environment-variables)
- [Usage](#usage)
- [Security](#security)
- [Database](#database)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

## Overview

Keeping track of upcoming contests can be difficult when you only want alerts for a particular Codeforces division. This bot checks the official Codeforces contest list and sends Telegram messages about upcoming contests that match each user's saved preference.

Choose **Div. 1**, **Div. 2**, **Div. 3**, **Div. 4**, or **All Divisions**. Preferences and notification history are stored locally in SQLite, so they persist between bot restarts.

## Features

- **Division-based alerts:** Select one Codeforces division or receive alerts for all divisions. A division is matched when it is explicitly named in the contest title.
- **Persistent preferences:** Save a division and notification status for each Telegram user.
- **Automatic monitoring:** Check the Codeforces contest list at startup and every five minutes afterward.
- **Telegram notifications:** Receive a message with the contest name, division, start date and time (India Standard Time), and contest link.
- **SQLite storage:** Keep user preferences, contests, and notification history in a local database.
- **Duplicate prevention:** Record notifications by user and contest so the same contest is not repeatedly sent to the same user.
- **Notification controls:** Pause and resume alerts without deleting a saved division.
- **Error handling and logging:** Log Codeforces API failures and unexpected monitoring errors; release a notification record if Telegram cannot deliver a message, so a later check can retry.
- **First-run baseline:** Existing contests are recorded at startup rather than treated as newly announced contests.

## Available commands

| Command | Description |
| --- | --- |
| `/start` | Start the bot. If no division is saved, choose one; otherwise view your saved settings. |
| `/change` | Choose a different division. |
| `/status` | View your saved division and whether notifications are enabled. |
| `/stop` | Disable notifications while keeping your saved division. |
| `/resume` | Re-enable notifications for your saved division. |
| `/help` | Show the bot's command list. |

The bot also echoes ordinary text messages that are not commands.

## How it works

1. A user starts a conversation with the bot using `/start`.
2. The bot asks the user to select a division.
3. The selected division and enabled notification status are saved in SQLite.
4. The bot checks the official Codeforces contest list at startup and every five minutes.
5. When a newly observed, upcoming contest title explicitly matches the user's selected division, the bot sends a Telegram notification. **All Divisions** matches every contest.
6. The user can change their division with `/change`, or pause and resume notifications with `/stop` and `/resume`.

## Technology stack

- **Python 3.10 or later**
- **python-telegram-bot** for Telegram bot commands and messaging
- **Codeforces API** (`contest.list`) for contest data
- **HTTPX** for asynchronous API requests
- **SQLite** for local persistence
- **python-dotenv** for loading local environment variables from `.env`
- **tzdata** and Python's `zoneinfo` for India Standard Time formatting
- **Git and GitHub** for version control and source hosting

## Project structure

```text
codeforces-telegram-bot/
├── .env.example       # Example environment configuration (no real credentials)
├── .gitignore         # Excludes local credentials, database, and generated files
├── bot.py             # Telegram commands, startup, and application lifecycle
├── codeforces.py      # Codeforces API client, contest monitor, and notifications
├── database.py        # SQLite schema and persistence operations
├── requirements.txt   # Python dependencies
├── README.md
├── .env               # Create locally; ignored by Git
└── bot.db             # Created locally when the bot runs; ignored by Git
```

The `.env` and `bot.db` entries are local runtime files; they are not included in the repository. A virtual environment such as `.venv/` is also local and ignored by Git.

## Installation and setup

### Prerequisites

- Windows with Python 3.10 or later installed and available through the Python launcher (`py`)
- Git for Windows
- A Telegram bot token created with [BotFather](https://t.me/BotFather)

### Set up on Windows PowerShell

1. Clone the repository and enter its folder:

   ```powershell
   git clone https://github.com/Lightgeet/codeforces-telegram-bot.git
   Set-Location .\codeforces-telegram-bot
   ```

2. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, allow scripts for this terminal session only, then activate again:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```

3. Install the project dependencies:

   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

4. Create your local environment file from the example and edit it:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   Replace the placeholder value for `TELEGRAM_BOT_TOKEN` with the token from BotFather. Do not paste the token into source code, this README, or a public chat.

5. Start the bot:

   ```powershell
   python .\bot.py
   ```

Keep the process running to monitor contests. Stop it with **Ctrl+C**.

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Yes | Token for the Telegram bot, loaded from `.env` or the process environment. |
| `BOT_DATABASE_PATH` | No | SQLite database file path. Defaults to `bot.db` beside `bot.py`. |

The checked-in `.env.example` contains a placeholder for `TELEGRAM_BOT_TOKEN`. An optional database path can be added to your local `.env`, for example:

```dotenv
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
BOT_DATABASE_PATH=bot.db
```

Replace the token placeholder locally; never commit the resulting `.env` file.

## Usage

1. Find your bot in Telegram by its username and press **Start**, or send `/start`.
2. Tap a division button to save your preference. Notifications are enabled when a division is saved.
3. Use `/status` to check your saved division and notification status.
4. Use `/change` to select another division.
5. Use `/stop` to pause alerts and `/resume` to turn them back on.

The bot only notifies users about upcoming contests observed after their preference was saved or updated. Contest divisions are determined from division text in the contest title; titles without an explicit division do not match an individual division, but are included for **All Divisions**.

## Security

- Treat your Telegram bot token like a password: anyone who obtains it may be able to control your bot.
- Keep `.env` local. The repository's `.gitignore` excludes `.env` and other `.env.*` files while allowing `.env.example`.
- Never commit tokens, passwords, private keys, or other credentials. Use placeholders in examples and keep real values in local environment configuration.
- If a token is exposed, open [BotFather](https://t.me/BotFather), select your bot, and use `/revoke` to invalidate the exposed token and generate a replacement. Update your local `.env` with the new token.
- The SQLite database contains Telegram user IDs, preferences, and notification history. Do not publish or commit your local database.

## Database

The bot creates a local SQLite database on startup (by default, `bot.db` beside `bot.py`). It initializes these tables:

- `users` stores Telegram user IDs, selected divisions, notification status, and timestamps.
- `contests` stores observed contest details, classified divisions, and whether a contest was part of the initial baseline.
- `notification_history` records a user/contest pair to prevent duplicate alerts.
- `app_state` stores application state used to distinguish the first contest check from later checks.

Database files and their SQLite journal files are excluded from Git. Back up the database separately if you need to preserve preferences and notification history.

## Deployment

The project currently documents local execution and does not include deployment configuration. For continuous notifications, a future deployment could run the bot as a long-lived process on a server with persistent storage for the SQLite database and a securely configured `TELEGRAM_BOT_TOKEN`. No hosted deployment is implied.

## Contributing

Contributions are welcome:

1. Fork the repository and create a branch for your change.
2. Set up the project locally using the installation steps above.
3. Make and test your change, keeping credentials and local database files out of commits.
4. Commit your work with a clear message and push the branch to your fork.
5. Open a pull request describing the change.

## License

There is currently no `LICENSE` file in this repository, so the project has no specified license.
