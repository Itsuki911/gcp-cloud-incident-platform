from collections.abc import Iterator
# データベースセッションを提供するためのイテレータ

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
#DeclarativeBase : ORM(Object-Relational Mapping)モデルの定義
#ORMは、データベースのテーブルとPythonのクラスを対応付ける手法
#データベースとの会話（トランザクション）を扱う
#個別の Session を生成するためのファクトリを生成

from incident_platform.config import get_settings
#condigから設定オブジェクトを取得する

class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True) # pool_pre_ping=True: 接続前に簡単な生存確認を行う。
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False) # 新しいDBセッションを生成するためのファクトリ


def get_session(request: Request) -> Iterator[Session]:
    """Provide one database session for each request."""

    session_factory = request.app.state.session_factory
    with session_factory() as session:
        yield session
