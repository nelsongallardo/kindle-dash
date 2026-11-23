# kindle-dash

An e-ink dashboard for a jailbroken Kindle Scribe. The Mac mini serves these screens on port 8090:

- **Paper**: *The Morning Scribe*, a three-page morning newspaper. Page 1 has the lead story, weather with a 24-hour temperature and rain chart, Tube status, and each holding's move at the last close. Page 2 has technology stories and the week ahead for markets. Page 3 has the topics people are discussing on X, each disrupted Tube line with its status, and the rest of today's events. Swipe left or right to turn pages, as in a Kindle book, or tap 1, 2 or 3 at the bottom. Swipes come from the Kindle's own `kindle.gestures.onswipe` API, because the app runtime sends no touch events to pages; `kindle/app/config.xml` must enable the `swipe` gesture. A Hermes agent writes the stories each morning (see [The Morning Scribe](#the-morning-scribe)).
- **Today**: current weather, a rain warning when rain is likely in the next 12 hours, Tube and Elizabeth line disruptions from the [TfL status API](https://api.tfl.gov.uk) (no key; "Good service on all lines" when there are none), the rest of today's events, tomorrow's first events, and how many lights are on.
- **Feed**: the three newest tweets worth reading from the X Following timeline, each with a headline and a one-sentence summary in large type, readable from across the room. A local model picks and summarises them (see [Feed](#feed)).
- **Home**: one tile per Home Assistant `light.*` entity (tap to toggle), plus All on and All off.
- **Calendar**: the next 7 days from one or more Google Calendar secret iCal links.
- **Weather**: current conditions, the next 12 hours and the next 5 days from [Open-Meteo](https://open-meteo.com) (no API key), with an icon per condition. The location is Home Assistant's home location, rounded to 2 decimal places (about 1 km) before it is sent.

`/` opens the first rotating screen. Today, Feed, Calendar and Weather rotate every `KINDLE_DASH_ROTATE_SECONDS`; each change reloads the data. Before `KINDLE_DASH_PAPER_UNTIL_HOUR` (10:00), once today's paper exists, its three pages lead the rotation and stay up for `KINDLE_DASH_PAPER_SECONDS` each. Home goes back to the rotation after `KINDLE_DASH_HOME_IDLE_SECONDS` without a tap.

To save battery, the Kindle sleeps at night: at `SLEEP_AT` (default 23:00) it goes to its sleep screen and suspends, with a timed wake-up at `WAKE_AT` (default 07:00), when it reopens the dashboard. Woken by hand during the night, it shows the dashboard for 5 minutes and sleeps again. See `kindle/scripts/night.sh`.

<img src="docs/weather.png" alt="Weather screen on the Kindle: current conditions, next hours and next days" width="465">

The Kindle shows them in a Kindle web app (`dev.kindledash`) that opens full-screen at boot. Secrets stay on the Mac; the Kindle only loads the pages.

## Mac mini

| Item | Value |
|---|---|
| Entry point | `kindle-dash` → `kindle_dash.app:main`, listens on `0.0.0.0:8090` |
| Service | launchd `local.kindle-dash` (`deploy/local.kindle-dash.plist`, installed in `~/Library/LaunchAgents/`) |
| Logs | `logs/stdout.log`, `logs/stderr.log` |
| Python | Homebrew `python3.14`. The macOS firewall allows incoming connections for that binary; it blocks the Pythons `uv` downloads, so the Kindle can't reach a server running on one. |

Settings come from `.env` (git-ignored, mode 600), all prefixed `KINDLE_DASH_`:

| Variable | Default | Meaning |
|---|---|---|
| `KINDLE_DASH_HA_TOKEN` | unset | Home Assistant long-lived access token. Without it, Home and Weather show "token not set". |
| `KINDLE_DASH_HA_URL` | `http://127.0.0.1:8123` | Home Assistant base URL |
| `KINDLE_DASH_CALENDAR_ICS_URLS` | `[]` | JSON list of secret iCal URLs |
| `KINDLE_DASH_CALENDAR_DAYS` | `7` | Days shown on Calendar |
| `KINDLE_DASH_TIMEZONE` | `Europe/London` | Time zone for the clock and events |
| `KINDLE_DASH_WEATHER_PLACE` | unset | Place name shown on Weather, such as `London`. Display only: the forecast location comes from Home Assistant. |
| `KINDLE_DASH_ROTATE_SECONDS` | `60` | Time on each rotating screen (Today, Feed, Calendar, Weather). Each change flashes the e-ink screen. |
| `KINDLE_DASH_HOME_IDLE_SECONDS` | `120` | Time on Home before returning to the rotation |
| `KINDLE_DASH_PAPER_DIR` | `data/paper` | Where `kindle-dash-paper` writes the daily paper (git-ignored) |
| `KINDLE_DASH_PAPER_UNTIL_HOUR` | `10` | The paper leads the rotation before this hour |
| `KINDLE_DASH_PAPER_SECONDS` | `120` | Time on each paper page |
| `KINDLE_DASH_FEED_DIR` | `data/feed` | Where `kindle-dash-feed` keeps `feed.json` (git-ignored) |
| `KINDLE_DASH_FEED_START_HOUR`, `KINDLE_DASH_FEED_END_HOUR` | `7`, `23` | The feed job does nothing outside these hours |
| `KINDLE_DASH_FEED_MODEL` | `qwen3.6-35b-a3b-dwq` | LM Studio model that picks the tweets |
| `KINDLE_DASH_FEED_INTERESTS` | AI, developer tools, technology companies and markets | What the reader follows, put into the model's prompt |
| `KINDLE_DASH_LMSTUDIO_URL` | `http://127.0.0.1:1234/v1` | LM Studio's OpenAI-compatible API |
| `KINDLE_DASH_HERMES_BROWSER` | `~/.hermes/browser/hermes-browser` | `playwright-cli` wrapper attached to the logged-in browser |

After changing code or `.env`, restart the service:

```bash
launchctl kickstart -k gui/$(id -u)/local.kindle-dash
```

Checks:

```bash
uv run ruff check . && uv run pyright && uv run pytest
```

## The Morning Scribe

A Hermes cron job (`morning-paper`, 06:45 Europe/London) follows [`hermes/morning-paper.md`](hermes/morning-paper.md). The agent only writes the stories; prices and the layout are ordinary code.

1. `uv run kindle-dash-paper prepare` reads holdings from the `ledgi` CLI and each holding's move at the last close from Yahoo Finance's chart endpoint. It writes `data/paper/<date>.prepared.json`. Mutual funds and stablecoins are skipped; a GBP ETF gets the London `.L` symbol.
2. The agent researches news on publisher pages and reads X (read only) in the shared logged-in browser, then writes `data/paper/<date>.stories.json`.
3. `uv run kindle-dash-paper publish <stories.json>` validates the stories against the schema (`uv run kindle-dash-paper schema`). Text over the length the page can hold, or a note for a symbol not in the portfolio, fails with exit 1 and the agent fixes it. On success it writes `data/paper/<date>.json`, which the dashboard reads.

If no paper exists for today, the Paper pages say so and the rotation skips them. The masthead font is [UnifrakturMaguntia](https://fonts.google.com/specimen/UnifrakturMaguntia) (SIL Open Font License, `src/kindle_dash/static/fonts/`); the other fonts are the Kindle's own.

## Feed

launchd `local.kindle-dash-feed` (`deploy/local.kindle-dash-feed.plist`) runs `kindle-dash-feed` every 15 minutes and logs to `logs/feed.log`. No cloud model is involved.

1. `src/kindle_dash/x_timeline.js` runs through `hermes-browser run-code`. It opens its own tab on x.com/home, selects Following, scrolls, records X's `HomeLatestTimeline` JSON responses, and closes the tab. It only reads.
2. `parse_timeline` turns that JSON into tweets: ads are dropped, retweets become the original tweet, thread replies and long posts are included, and `t.co` links become their display text.
3. Only tweets from the last 24 hours that were not in an earlier run go to the local model (LM Studio, loaded on demand and unloaded after 5 idle minutes). It returns at most 5 picks with a headline, a one-sentence summary and an importance from 1 to 5. Picks below 4, over the length limits, or for a tweet not in the batch are dropped.
4. `data/feed/feed.json` keeps the last 30 picks, with the original tweet text, and the IDs of tweets already sent to the model. If the browser or model fails, nothing is saved and the next run sends the same tweets.

Try it without saving: `uv run kindle-dash-feed --dry-run`.

## Kindle

`ssh kindle` reaches the Kindle over Wi-Fi through a reverse tunnel (see `kindle/scripts/tunnel.sh`).

The files in `kindle/` and `deploy/` contain placeholders: `__MAC_HOST__` (the Mac mini's LAN address), `__MAC_USER__` (its account) and `__PROJECT_DIR__` (this checkout). `deploy/install.sh` fills them in, installs the launchd services, copies the Kindle files and registers the app. It is safe to rerun:

```bash
MAC_HOST=192.168.1.10 deploy/install.sh
```

`MAC_USER` defaults to the current account. `SLEEP_AT` and `WAKE_AT` (24-hour `HH:MM`) set the night window. The script does not create keys: the tunnel key (`/var/local/kindle-dash/tunnel_key`), its tunnel-only entry in the Mac's `~/.ssh/authorized_keys`, and the `kindle` entry in `~/.ssh/config` are set up once by hand.

| Repo file | Installed at | Purpose |
|---|---|---|
| `kindle/app/config.xml`, `index.html` | `/var/local/mesquite/kindledash/` | The `dev.kindledash` web app. `index.html` redirects to the Mac. |
| `kindle/scripts/start.sh` | `/mnt/us/kindle-dash/start.sh` | Keeps the screen awake, waits for the server, opens the app. The library item `Dashboard.sh` runs it. |
| `kindle/scripts/stop.sh` | `/mnt/us/kindle-dash/stop.sh` | Lets the Kindle sleep again (library item `Dashboard - allow sleep.sh`). |
| `kindle/scripts/tunnel.sh` | `/var/local/kindle-dash/tunnel.sh` | Local-only SSH server on `127.0.0.1:2022`, forwarded to the Mac's `localhost:2222`. |
| `kindle/upstart/kindle-dash-open.conf` | `/etc/upstart/` | Runs `start.sh` after `home_wait` at boot. |
| `kindle/upstart/kindle-dash-tunnel.conf` | `/etc/upstart/` | Runs `tunnel.sh` at boot. |
| `kindle/scripts/night.sh` | `/var/local/kindle-dash/night.sh` | Night sleep and morning wake-up. Logs to `/var/local/kindle-dash/night.log`. |
| `kindle/upstart/kindle-dash-night.conf` | `/etc/upstart/` | Runs `night.sh` at boot. |
| `kindle/library/*.sh` | `/mnt/us/documents/` | Library items **Dashboard** and **Dashboard - allow sleep**. |

The app is registered in `/var/local/appreg.db` with the same rows as the built-in `com.lab126.webview` app. A copy of the database from before registration is at `/var/local/kindle-dash/appreg.db.bak`.

`/etc/upstart` is on the read-only root partition. Run `mntroot rw` before changing a file there and `mntroot ro` after.

The app's web engine is WebKitGTK 1.0 (about Safari 5). Templates use table layouts, not grid or flexbox, and ES5 JavaScript. The app renders at 1860px without scaling, so `base.html` sets `zoom: 2` when `window.innerWidth > 1300`.
