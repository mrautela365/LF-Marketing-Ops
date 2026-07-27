# Backend Import Guide

**Quick reference for how to import from the reorganized backend.**

---

## ✅ Old Style (Still Works — No Changes Needed)

If you have existing code, nothing needs to change:

```python
# These all work exactly as before
import agent
from event_brands import lookup_event_brand
from hubspot_tools import clone_email
from stage_detector import detect_stage
import asana_tools
from content_tools import fetch_url
import email_templates
from llm_gateway import call_llm
```

**Why?** Wrapper files in the root backend directory re-export from the new locations.

---

## 🎯 New Style (Recommended for New Code)

### Core Agent Functions
```python
# Main orchestration functions
from core import plan_turn, clone_turn, content_turn, chat_turn
from core import SYSTEM_PROMPT, TOOLS
from core import session_store  # Session management
```

### Utilities
```python
# Campaign stage detection
from utils import detect_stage, MARKETING_JOURNEY

# Event brand lookup
from utils import lookup_event_brand, get_brand_events, expand_location_words

# Content tools
from utils import fetch_url, prepare_content
```

### Integrations (External APIs)
```python
# HubSpot email operations
from integrations import (
    clone_email,
    create_ab_variation,
    update_email_settings,
    update_email_content,
    set_email_send_list,
    validate_staged_email,
    search_hubspot_lists,
)

# HubSpot brand lookup
from integrations import lookup_brand_history, get_email_campaign

# Asana integration
from integrations import create_asana_task, update_asana_task

# UTM building
from integrations import build_utm_params
```

### Templates
```python
# Standard email templates
from templates import get_template, template_exists

# AI-generated email templates (by stage)
from templates import AI_STAGE_TEMPLATES, map_funnel_stage_to_ai_template
```

### LLM Gateway
```python
# Unified LLM routing
from llm import call_llm, CLAUDE_MODEL
```

---

## 📁 Directory Reference

| Directory | Use For | Example Import |
|-----------|---------|-----------------|
| `core/` | Agent orchestration, sessions | `from core import plan_turn` |
| `integrations/` | External APIs (HubSpot, Asana, UTM) | `from integrations import clone_email` |
| `templates/` | Email template definitions | `from templates import AI_STAGE_TEMPLATES` |
| `utils/` | Shared utilities & helpers | `from utils import detect_stage` |
| `llm/` | LLM backend routing | `from llm import call_llm` |

---

## 🔄 Migration Guide (Optional)

### If You Want to Update Existing Code

**Before (Old Style):**
```python
import agent
from event_brands import lookup_event_brand
from hubspot_tools import clone_email

def my_function():
    brand = lookup_event_brand(url)
    email = clone_email(source_id, name)
```

**After (New Style):**
```python
from core import plan_turn
from utils import lookup_event_brand
from integrations import clone_email

def my_function():
    brand = lookup_event_brand(url)
    email = clone_email(source_id, name)
```

**Change:** Only the `import` statements change. Function calls stay identical.

---

## 📝 Adding New Code

### Where to Add It?

**Is it...?** → **Add to...**

- Agent logic (plan_turn, clone_turn) → `core/agent.py`
- Session management → `core/session.py`
- HubSpot API calls → `integrations/hubspot.py`
- Asana API calls → `integrations/asana.py`
- URL/location building → `integrations/utm.py`
- Campaign stage detection → `utils/stage_detector.py`
- Event brand lookup → `utils/event_brands.py`
- Content fetching/parsing → `utils/content_tools.py`
- Email template definitions → `templates/email_templates.py`
- AI template definitions → `templates/ai_email_templates.py`
- LLM routing logic → `llm/gateway.py`
- High-level business logic → `services/` (future)

---

## ❓ FAQ

**Q: Do I have to change my imports?**  
A: No. Old imports work via wrappers. But new imports are cleaner for new code.

**Q: Will my code break if I keep using old imports?**  
A: No. They're guaranteed to work.

**Q: When should I update to new imports?**  
A: When writing new code or refactoring. No rush.

**Q: Can I mix old and new imports?**  
A: Yes. Both work identically.

**Q: What if I import something that doesn't exist?**  
A: Same as before — Python will raise ImportError. The module structure doesn't change that.

---

## 🧪 Testing Imports

Verify imports work with Python REPL:

```python
# Old style
from event_brands import lookup_event_brand  # Works!

# New style
from utils import lookup_event_brand  # Works!

# Both import the same function
# They're identical
```

---

## 📚 See Also

- `STRUCTURE.md` — Detailed module documentation
- `RESTRUCTURING_SUMMARY.md` — What changed and why
- Original `backend/README.md` (if exists) — Project-specific info

