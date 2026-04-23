from flask import Flask
from config import MAX_CONTENT_LENGTH
from database import init_db
from routes.main import main_bp
from routes.sessions import sessions_bp
from routes.records import records_bp

def create_app():
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

    # 初始化数据库
    init_db()

    # 注册蓝图
    app.register_blueprint(main_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(records_bp)

    return app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
