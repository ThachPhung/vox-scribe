"""Khởi tạo SQLite và nạp extension sqlite-vec."""
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

import sqlite_vec

from core_app.database.models import MIGRATIONS, SCHEMA_VERSION


class SchemaVersionError(RuntimeError):
    pass


def open_connection(db_path: Path) -> sqlite3.Connection:
    """Mỗi request dùng một kết nối riêng; FastAPI có thể tạo và dùng nó ở hai luồng khác nhau."""
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    return connection


@contextmanager
def write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Giữ khóa ghi từ lệnh đọc đầu tiên, để bước kiểm tra và bước ghi không bị request khác chen vào."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    connection.commit()


def initialize_database(db_path: Path) -> None:
    """Tạo bảng hoặc nâng cấp lên SCHEMA_VERSION; mỗi bước nâng cấp thành công trọn vẹn hoặc không đổi gì."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(open_connection(db_path)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        current_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if current_version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"DB tại {db_path} có schema v{current_version}, code chỉ hỗ trợ tới v{SCHEMA_VERSION}"
            )
        for version in range(current_version + 1, SCHEMA_VERSION + 1):
            connection.executescript(
                f"BEGIN;\n{MIGRATIONS[version]}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
