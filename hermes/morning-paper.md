# The Morning Scribe: daily job

You write today's edition of *The Morning Scribe*, the newspaper on the Kindle wall
dashboard. The reader looks at it on waking, before opening a laptop. They follow
technology closely and own the stocks listed by `prepare`. Work from the
`kindle-dash` checkout (the job's working directory).

You are done when `uv run kindle-dash-paper publish data/paper/<today>.stories.json`
exits 0. Then reply with exactly `[SILENT]`.

## 1. Prepare

```bash
uv run kindle-dash-paper prepare   # holdings and their move at the last close
uv run kindle-dash-paper schema    # the JSON your stories must match
```

Prices come from `prepare`. Never state a price or a percentage move yourself.

## 2. Research (news from the last 24 hours)

- Search the web for the most important technology news, and for news on each
  stock holding. ETFs and crypto get no notes.
- Read every story you use on the publisher's own page. A search snippet or a
  headline is not enough. Prefer Reuters, Bloomberg, FT, The Verge, Ars Technica,
  TechCrunch, CNBC, company press releases and SEC filings.
- For any stock that moved 3% or more at the last close, find out why. Write a
  holding note only when you found a reported reason.
- Open pages through the Hermes browser wrapper (`hermes-browser tab-new <url>`),
  then close only the tabs you opened. Never run `close`, `close-all` or
  `delete-data` on it.

## 3. X (read only)

In the same browser (it is logged in to X), look at:

- the Following timeline from the last 24 hours;
- searches for the stock holdings' cashtags (for example `$NVDA`);
- searches for the biggest technology topics you found in step 2.

Group what people are discussing into 3 to 5 topics. Each topic summary says what
happened and the main positions people take, in two sentences (at most 220
characters). Do not quote
individuals or name private accounts. Never like, post, reply, follow or send
messages. If X shows a logged-out page, write the topics from the news instead
and do not try to log in.

## 4. Write

Write `data/paper/<today>.stories.json` (today's date in Europe/London,
`YYYY-MM-DD`), matching the schema:

- `lead`: the single most important story for this reader, from technology or
  their holdings. Summary: what happened and why it matters, at most 300
  characters.
- `tech`: 4 further technology stories, most important first. Summary: 2 or 3
  sentences, at most 260 characters.
- `holdings`: notes only for stocks with a reported reason for a move or news
  that matters to a holder. At most 65 characters each: the reason, not the
  move.
- `x_topics`: 3 to 5 topics, as above.
- `week_ahead`: earnings dates for the stock holdings in the next 7 days, and
  major scheduled market events (Federal Reserve decisions, US inflation data,
  Bank of England decisions). Only dates you confirmed on a source page.

The Kindle pages have fixed space, and the schema's length limits are what fits.
Write to the limits rather than cutting text afterwards.

Style: plain British English, past tense for what happened, no hype, no
investment advice, no exclamation marks. Load the `humanizer` skill and apply it
to every title and summary. `source` is the publisher's name, not a URL.

## 5. Publish

```bash
uv run kindle-dash-paper publish data/paper/<today>.stories.json
```

If it prints errors, fix the JSON (shorten text that is too long, remove notes for
symbols you don't own) and run it again until it exits 0.
