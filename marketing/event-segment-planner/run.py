"""
Event Segment Planner - local web UI
Run:  .venv/Scripts/python run.py
Open: http://localhost:8081
"""

import webbrowser
from app import create_app

app = create_app()

if __name__ == "__main__":
    port = 8081
    print(f"\n  Event Segment Planner  ->  http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
