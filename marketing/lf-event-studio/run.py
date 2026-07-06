"""
LF Event Audience Studio — unified segment planning + list building
Run:  .venv/Scripts/python run.py
Open: http://localhost:8082
"""

import webbrowser
from app import create_app

app = create_app()

if __name__ == "__main__":
    port = 8082
    print(f"\n  LF Event Audience Studio  ->  http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
