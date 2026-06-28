from flask import Flask
from config import MAX_CONTENT_LENGTH
from database import init_db, close_db
from routes.main import main_bp
from routes.sessions import sessions_bp
from routes.records import records_bp
from logger import app_logger

def create_app():
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

    app_logger.info("正在初始化应用...")
    
    init_db()
    app_logger.info("数据库初始化完成")

    app.register_blueprint(main_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(records_bp)
    app_logger.info("路由注册完成")

    app.teardown_appcontext(close_db)

    return app

app = create_app()

if __name__ == '__main__':
    app_logger.info("启动 Flask 应用 - http://127.0.0.1:5000")
    app.run(debug=True, host='127.0.0.1', port=5000)
