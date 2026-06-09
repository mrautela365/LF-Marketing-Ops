import getpass
import httpx

def validate_anthropic_key(api_key: str) -> None:
    print("\nTesting Anthropic API key...")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-haiku-4-5",
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "say hi"}],
    }
    try:
        resp = httpx.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=10)
        if resp.status_code == 200:
            print("✅ VALID — Anthropic key works!")
        elif resp.status_code == 401:
            print("❌ INVALID — Key is wrong or revoked.")
        elif resp.status_code == 403:
            print("⚠️  FORBIDDEN — Key is valid but no permissions.")
        else:
            print(f"⚠️  Unexpected status: {resp.status_code} — {resp.text}")
    except Exception as e:
        print(f"❌ Connection error: {e}")


if __name__ == "__main__":
    print("=== API Key Validator ===")
    print("Your input will NOT be shown on screen.\n")
    key = getpass.getpass("Paste your API key: ").strip()

    if not key:
        print("No key entered.")
    elif key.startswith("sk-ant-"):
        validate_anthropic_key(key)
    else:
        print("⚠️  This does not look like an Anthropic key (should start with sk-ant-)")
        choice = input("Test it anyway? (y/n): ").strip().lower()
        if choice == "y":
            validate_anthropic_key(key)
