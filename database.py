from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
# 根據 SQLAlchemy 版本的不同，declarative_base 的引入位置可能不同
try:
    from sqlalchemy.orm import declarative_base
except ImportError:
    from sqlalchemy.ext.declarative import declarative_base

# 設定 SQLite 資料庫檔案名稱
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"

# 建立資料庫引擎
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# 建立資料庫連線的 Session 類別
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 創造 Base！(這裡才是 Base 的發源地，不能從 models 導入)
Base = declarative_base()