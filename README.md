# ga4-mcp

An MCP server that gives Claude (or any MCP client) read-only access to a Google Analytics 4 property's reporting data — traffic overview, top pages, traffic sources, and custom conversion/engagement events.

Built for goldvalleysolutions.com, but works for any GA4 property.

## Tools

- **ga4_traffic_overview** — sessions, active users, new users, engaged sessions, engagement rate for a date range.
- **ga4_top_pages** — top pages by views.
- **ga4_traffic_sources** — sessions broken down by channel (organic search, direct, referral, social, etc.).
- **ga4_conversion_summary** — counts for custom events (`form_submission`, `cta_click`, `project_click`, `scroll_depth` by default).
- **ga4_run_report** — flexible escape hatch: any GA4 dimensions + metrics combination.

All tools are read-only (no data is ever modified) and accept `start_date`/`end_date` as `YYYY-MM-DD` or GA4 relative keywords (`today`, `7daysAgo`, `28daysAgo`, etc.), plus a `response_format` of `markdown` or `json`.

## One-time Google Cloud setup

1. **Enable the API.** In the [Google Cloud Console](https://console.cloud.google.com/), select (or create) a project, then go to "APIs & Services" > "Library", search for **Google Analytics Data API**, and click Enable.
2. **Create a service account.** "APIs & Services" > "Credentials" > "Create Credentials" > "Service account". Give it any name (e.g. `ga4-mcp-reader`). No project-level IAM role is needed — access is granted at the GA4 property level in step 4.
3. **Create a JSON key.** Open the new service account > "Keys" tab > "Add Key" > "Create new key" > JSON. This downloads a `.json` file — save it somewhere safe on your machine (**not** inside this repo; it's gitignored, but keep it outside the folder entirely to be safe, e.g. `~/.config/ga4-mcp/service-account.json`).
4. **Grant the service account access to GA4.** In [Google Analytics](https://analytics.google.com/), go to Admin > Property Access Management (for the goldvalleysolutions.com property) > "+" > Add users. Paste in the service account's email address (looks like `ga4-mcp-reader@your-project.iam.gserviceaccount.com`, found on the service account's details page) and give it the **Viewer** role.
5. **Find your GA4 Property ID.** Admin > Property Settings. It's a number like `123456789` — not the same as the `G-XXXXXXX` measurement ID used in the site's tracking snippet.

## Install & configure

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env: set GOOGLE_APPLICATION_CREDENTIALS to the path from step 3,
# and GA4_PROPERTY_ID to the number from step 5
```

## Run it / connect it to Claude

For local/stdio use (Claude Desktop, Claude Code, Cowork), add it as an MCP server pointing at:

```
python3 /absolute/path/to/ga4_mcp.py
```

with the environment variables from `.env` set in whatever config mechanism your client uses (Claude Desktop's `claude_desktop_config.json` `env` block, for example).

You can also run it directly to sanity-check it starts cleanly:

```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json GA4_PROPERTY_ID=123456789 python3 ga4_mcp.py
```

## Security notes

- The service account only ever needs **Viewer** access — never grant it Editor/Admin on the GA4 property.
- Never commit the service account JSON key or `.env` file — both are already covered by `.gitignore`.
- All tools are read-only against the GA4 Data API; nothing in this server can modify your Analytics configuration or data.
