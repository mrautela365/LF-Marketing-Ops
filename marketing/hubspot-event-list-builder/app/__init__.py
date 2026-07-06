from flask import Flask


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates")

    @app.after_request
    def add_cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    from .routes import bp
    app.register_blueprint(bp)

    return app
