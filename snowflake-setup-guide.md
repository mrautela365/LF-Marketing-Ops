# Connecting to Snowflake through Claude Code

This guide explains how we connect Claude Code to Snowflake for querying data and powering the Marketing Ops Dashboard.

## How It Works

We use a shared Node.js module (`snowflake-connection.js`) that handles authentication and query execution. Claude Code runs export scripts that use this module to query Snowflake, write JSON files, and push them to GitHub (which triggers a Render deploy).

## Prerequisites

1. **Node.js** installed (we use nvm)
2. **Snowflake access** — you need a Snowflake username and either a private key or password
3. **snowflake-sdk** npm package installed in your working directory

## Setup Steps

### 1. Generate an RSA Key Pair (for key-pair auth)

```bash
# Generate private key (unencrypted for automation)
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/rsa_key.p8 -nocrypt

# Generate public key
openssl rsa -in ~/rsa_key.p8 -pubout -out ~/rsa_key.pub
```

Then ask a Snowflake admin to assign your public key to your user:
```sql
ALTER USER YOUR_USERNAME SET RSA_PUBLIC_KEY='<paste public key without headers>';
```

### 2. Create `.env` File

Create a `.env` file in your working directory:

```env
# Snowflake Configuration
SNOWFLAKE_ACCOUNT=JNMHVWD-XPB85243
SNOWFLAKE_USERNAME=DEV_YOURNAME
SNOWFLAKE_PRIVATE_KEY_PATH=/Users/yourname/rsa_key.p8
SNOWFLAKE_ROLE=PUBLIC

# Snowflake resources
SNOWFLAKE_WAREHOUSE=ADHOC_REPORTING
SNOWFLAKE_DATABASE=HUBSPOT_INGEST
SNOWFLAKE_SCHEMA=V2_LIVE
```

**Alternative auth methods** (in priority order):
- `SNOWFLAKE_TOKEN` — OAuth token (best for API/cloud access)
- `SNOWFLAKE_PASSWORD` — password auth (simplest)
- `SNOWFLAKE_PRIVATE_KEY` — private key content as env var (best for Render/cloud)
- `SNOWFLAKE_PRIVATE_KEY_PATH` — path to private key file (best for local dev)
- `SNOWFLAKE_AUTHENTICATOR=externalbrowser` — opens browser for SSO (interactive only)

### 3. Install Dependencies

```bash
npm install snowflake-sdk dotenv
```

### 4. Copy `snowflake-connection.js`

Copy the connection module from `markdash-biweekly-playground/snowflake-connection.js` to your working directory. This module exports:

- `executeQuery(sqlText)` — runs a SQL query and returns rows
- `testConnection()` — verifies your connection works

### 5. Test Your Connection

```bash
node -e "
const { testConnection } = require('./snowflake-connection');
testConnection().then(r => console.log('Connected! Version:', r[0]['CURRENT_VERSION()']));
"
```

## Using It with Claude Code

Once set up, you can ask Claude to query Snowflake directly. Examples:

- "Query Snowflake for all email data since January"
- "Run this SQL against Snowflake: SELECT ..."
- "Export this data to a JSON file for the dashboard"

Claude will use the `snowflake-connection.js` module and your `.env` credentials to execute queries.

## Writing Export Scripts

Export scripts follow this pattern:

```javascript
const { executeQuery } = require('./snowflake-connection');
const fs = require('fs');
require('dotenv').config();

async function exportData() {
    try {
        const rows = await executeQuery(`
            SELECT column1, column2
            FROM your_table
            WHERE conditions
        `);
        console.log('Got ' + rows.length + ' rows');

        // Transform and write JSON
        var result = { /* structured data */ };
        var outputPath = '/path/to/markdash-biweekly/public/your_data.json';
        fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
        console.log('Wrote ' + outputPath);
    } catch (error) {
        console.error('ERROR:', error.message);
        process.exit(1);
    }
}

exportData();
```

## Current Export Scripts

| Script | Data | Output |
|---|---|---|
| `export_email_data.js` | HubSpot email campaigns | `email_data_by_month.json` |
| `export_web_activity.js` | Web sessions & page views | `web_activity_data.json` |
| `refresh_attribution_data.js` | Marketing attribution | `attribution_data.json` |
| `export_social_accounts.js` | Social media profiles | `social_accounts_data.json` |
| `export_social_data.js` | Social listening/hashtags | `social_listening_data.json` |
| `export_paid_ads_data.js` | Paid ads campaigns | `paid_ads_campaign_data.json` + `paid_ads_platform_data.json` |
| `export_lf_education_coupons.js` | LF Education coupon fulfillment | `lf_education_coupons.json` |

## Daily Refresh

All scripts run daily at 10:00 AM PT via a macOS launchd job (`com.markdash.daily-refresh.plist`). The refresh script (`refresh_all.sh`) runs each export, then commits and pushes any changed JSON files to GitHub, which triggers a Render deploy.

## Key Snowflake Tables

- `hubspot_ingest.v2_daily.objects_marketing_emails` — Email campaign data
- `hubspot_ingest.v2_daily.objects_contacts` — Contact records
- `hubspot_ingest.v2_daily.EVENTS_MTA_DELIVERED_EMAIL_V2` — Email delivery events
- `hubspot_ingest.v2_daily.EVENTS_MTA_BOUNCED_EMAIL_V2` — Email bounce events
- `ANALYTICS.SILVER_FACT.SOCIAL_MEDIA_PROFILE_ANALYTICS` — Social accounts data
- `ANALYTICS.SILVER_SEGMENT.LF_EDUCATION_BENEFIT_TRIGGERS_7_DAYS` — LF Education coupon eligibility

## Troubleshooting

- **"node: command not found"** in cron/launchd — Add nvm sourcing to your script:
  ```bash
  export NVM_DIR="$HOME/.nvm"
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  ```
- **Auth error** — Check that your private key matches the public key registered in Snowflake
- **Table not found** — You may need a different role. Check with Snowflake admin.
