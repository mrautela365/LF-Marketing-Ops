# Connecting to Snowflake through Claude Code

How to set up Claude Code to query Snowflake directly using Node.js and key-pair authentication.

## Prerequisites

1. **Node.js** installed (we use nvm)
2. **Snowflake access** — you need a Snowflake username and role
3. **Claude Code** installed

## Setup Steps

### 1. Generate an RSA Key Pair

```bash
# Generate private key (unencrypted for automation)
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/rsa_key.p8 -nocrypt

# Generate public key
openssl rsa -in ~/rsa_key.p8 -pubout -out ~/rsa_key.pub
```

Then ask a Snowflake admin to assign your public key to your user:
```sql
ALTER USER YOUR_USERNAME SET RSA_PUBLIC_KEY='<paste public key content without BEGIN/END headers>';
```

### 2. Install Dependencies

```bash
npm install snowflake-sdk dotenv
```

### 3. Create `.env` File

Create a `.env` file in your working directory:

```env
# Snowflake Configuration
SNOWFLAKE_ACCOUNT=YOUR_ORG-YOUR_ACCOUNT
SNOWFLAKE_USERNAME=DEV_YOURNAME
SNOWFLAKE_PRIVATE_KEY_PATH=/Users/yourname/rsa_key.p8
SNOWFLAKE_ROLE=PUBLIC

# Snowflake resources
SNOWFLAKE_WAREHOUSE=ADHOC_REPORTING
SNOWFLAKE_DATABASE=HUBSPOT_INGEST
SNOWFLAKE_SCHEMA=V2_LIVE
```

**Other auth methods** (if key-pair isn't an option):
- `SNOWFLAKE_PASSWORD` — password auth (simplest to set up)
- `SNOWFLAKE_AUTHENTICATOR=externalbrowser` — opens browser for SSO (interactive only, won't work in automation)

### 4. Add `snowflake-connection.js`

Create this file in your working directory:

```javascript
const snowflake = require('snowflake-sdk');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

function createConnection() {
    const config = {
        account: process.env.SNOWFLAKE_ACCOUNT,
        username: process.env.SNOWFLAKE_USERNAME,
        role: process.env.SNOWFLAKE_ROLE
    };

    if (process.env.SNOWFLAKE_PASSWORD) {
        config.password = process.env.SNOWFLAKE_PASSWORD;
    } else if (process.env.SNOWFLAKE_PRIVATE_KEY_PATH) {
        const privateKeyPath = path.resolve(process.env.SNOWFLAKE_PRIVATE_KEY_PATH);
        config.privateKey = fs.readFileSync(privateKeyPath, 'utf8');
        config.authenticator = 'SNOWFLAKE_JWT';
    }

    if (process.env.SNOWFLAKE_WAREHOUSE) config.warehouse = process.env.SNOWFLAKE_WAREHOUSE;
    if (process.env.SNOWFLAKE_DATABASE) config.database = process.env.SNOWFLAKE_DATABASE;
    if (process.env.SNOWFLAKE_SCHEMA) config.schema = process.env.SNOWFLAKE_SCHEMA;

    return snowflake.createConnection(config);
}

async function executeQuery(sqlText) {
    const connection = createConnection();
    try {
        await new Promise((resolve, reject) => {
            connection.connect((err, conn) => {
                if (err) return reject(err);
                resolve(conn);
            });
        });

        const rows = await new Promise((resolve, reject) => {
            connection.execute({
                sqlText: sqlText,
                complete: (err, stmt, rows) => {
                    if (err) return reject(err);
                    resolve(rows);
                }
            });
        });

        await new Promise((resolve) => {
            connection.destroy(() => resolve());
        });

        return rows;
    } catch (error) {
        try { await new Promise((resolve) => { connection.destroy(() => resolve()); }); } catch (e) {}
        throw error;
    }
}

module.exports = { executeQuery };
```

### 5. Test Your Connection

```bash
node -e "
const { executeQuery } = require('./snowflake-connection');
executeQuery('SELECT CURRENT_VERSION()').then(r => console.log('Connected! Version:', r[0]['CURRENT_VERSION()']));
"
```

You should see something like: `Connected! Version: 8.x.x`

## Using It with Claude Code

Once set up, you can ask Claude to query Snowflake in plain language:

- "Query Snowflake for all contacts where role is Technical Contact"
- "Run this SQL against Snowflake: SELECT ..."
- "How many rows are in the marketing_emails table?"

Claude uses the `snowflake-connection.js` module and your `.env` credentials to run queries and return results.

## Troubleshooting

| Problem | Fix |
|---|---|
| `node: command not found` (in cron/automation) | Add nvm sourcing: `export NVM_DIR="$HOME/.nvm"` and `[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"` |
| Auth error / JWT token invalid | Verify your private key matches the public key registered in Snowflake |
| Table not found / not authorized | You may need a different role — check with Snowflake admin |
| Connection timeout | Check that `SNOWFLAKE_ACCOUNT` is correct (format: `ORG-ACCOUNT`) |
