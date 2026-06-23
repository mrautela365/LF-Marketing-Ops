"""
/setup routes — credential management page and save endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..lib.credentials import (
    get_asana_pat,
    get_hubspot_api_key,
    is_asana_configured,
    is_hubspot_configured,
    save_credentials,
)
from ..models.email import ApiResponse, SaveCredentialsRequest

router = APIRouter()


@router.get("/setup", response_class=HTMLResponse)
async def setup_page() -> str:
    hubspot_masked = "●●●●" + get_hubspot_api_key()[-4:] if is_hubspot_configured() else ""
    asana_masked = "●●●●" + get_asana_pat()[-4:] if is_asana_configured() else ""
    hs_status = "✅ Configured" if is_hubspot_configured() else "❌ Not set"
    asana_status = "✅ Configured" if is_asana_configured() else "⚠️ Not set (optional)"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Setup — HubSpot Draft Email</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="setup-page">
<div class="setup-container">
  <h1>⚙️ Credential Setup</h1>
  <p class="subtitle">Configure your API credentials to connect to HubSpot.</p>

  <div class="status-grid">
    <div class="status-item">
      <strong>HubSpot API Key</strong>
      <span class="status-badge">{hs_status}</span>
      {f'<code class="masked">{hubspot_masked}</code>' if hubspot_masked else ''}
    </div>
    <div class="status-item">
      <strong>Asana PAT</strong>
      <span class="status-badge">{asana_status}</span>
      {f'<code class="masked">{asana_masked}</code>' if asana_masked else ''}
    </div>
  </div>

  <form id="setup-form">
    <div class="field-group">
      <label for="hubspot_api_key">
        HubSpot Private App Token <span class="required">*</span>
      </label>
      <input type="password" id="hubspot_api_key" name="hubspot_api_key"
             placeholder="pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
             autocomplete="off">
      <small>
        HubSpot → Settings → Integrations → Private Apps.<br>
        Required scopes: <code>marketing-email</code>, <code>communication-preferences</code>,
        <code>crm.lists.read</code>, <code>content</code>.
      </small>
    </div>

    <div class="field-group">
      <label for="asana_pat">
        Asana Personal Access Token <span class="optional">(optional)</span>
      </label>
      <input type="password" id="asana_pat" name="asana_pat"
             placeholder="1/xxxxxxxxxxxx..."
             autocomplete="off">
      <small>
        <a href="https://app.asana.com/0/my-apps" target="_blank">Asana → My Profile → Apps → Personal Access Tokens</a>
      </small>
    </div>

    <div class="form-actions">
      <button type="submit" class="btn-primary">Save Credentials</button>
      {"<a href='/' class='btn-secondary'>← Back to Email Manager</a>" if is_hubspot_configured() else ""}
    </div>
    <div id="setup-result" class="result-area hidden"></div>
  </form>
</div>

<script>
document.getElementById('setup-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const result = document.getElementById('setup-result');
  result.className = 'result-area';
  result.textContent = 'Saving...';
  const body = {{}};
  const hsKey = document.getElementById('hubspot_api_key').value.trim();
  const asanaPat = document.getElementById('asana_pat').value.trim();
  if (hsKey) body.hubspot_api_key = hsKey;
  if (asanaPat) body.asana_pat = asanaPat;
  try {{
    const res = await fetch('/api/setup', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body)
    }});
    const data = await res.json();
    if (data.success) {{
      result.className = 'result-area success';
      result.innerHTML = '✅ Credentials saved! <a href="/">Open Email Manager →</a>';
    }} else {{
      result.className = 'result-area error';
      result.textContent = '❌ ' + (data.error || 'Failed to save credentials.');
    }}
  }} catch (err) {{
    result.className = 'result-area error';
    result.textContent = '❌ Network error: ' + err.message;
  }}
}});
</script>
</body>
</html>"""


@router.post("/api/setup", response_model=ApiResponse)
async def save_setup(req: SaveCredentialsRequest) -> ApiResponse:
    if not req.hubspot_api_key and not req.asana_pat:
        return ApiResponse(success=False, error="At least one credential must be provided.")
    try:
        save_credentials(
            hubspot_api_key=req.hubspot_api_key,
            asana_pat=req.asana_pat,
        )
        return ApiResponse(
            success=True,
            data={
                "hubspot_configured": is_hubspot_configured(),
                "asana_configured": is_asana_configured(),
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))
