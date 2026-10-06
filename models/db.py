import datetime
import os

import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy.types import Text, TypeDecorator
from sqlmodel import Session, SQLModel, create_engine, select

load_dotenv()

from crypto_utils import decrypt, encrypt

# SQLite file, gitignored. DB_PATH overrides the default location (relative
# paths resolve against the repo root, not the cwd, so cron/scripts agree).
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(repo_root, os.environ.get("DB_PATH", "budget.db"))
db_url = f"sqlite:///{db_path}"


def utcnow():
    """Naive UTC timestamp — stored datetimes are treated as UTC everywhere
    (Flask serializes them with a GMT label, browsers convert to local)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


# One shared engine for the whole process. check_same_thread=False lets
# gunicorn/Flask threads share pooled connections (each Session still uses
# one connection at a time).
engine = create_engine(db_url, connect_args={"check_same_thread": False})


@sqlalchemy.event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    # SQLite ignores FOREIGN KEY constraints unless this is on per connection
    # (MySQL/InnoDB always enforced them, so keep that behaviour).
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL lets readers proceed while the cron importer is writing; busy_timeout
    # makes a second writer wait instead of failing with "database is locked".
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


class EncryptedString(TypeDecorator):
    """Transparently Fernet-encrypts a string column. Stored ciphertext is
    base64 and runs well past the plaintext length, so the underlying
    column type is TEXT rather than a fixed-length VARCHAR."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt(value)


class DBModel(SQLModel):
    # Pydantic generates __eq__ for model classes, which implicitly nulls
    # out __hash__ (Python's rule: define __eq__ without __hash__ and the
    # class becomes unhashable) — restore identity-based hashing so ORM
    # row objects can be used as dict keys / set members, as with plain
    # SQLAlchemy models.
    __hash__ = object.__hash__

    def create(self):
        try:
            self.model_validate(self)
            with Session(engine) as session:
                session.add(self)
                session.commit()
                session.refresh(self)
                return self
        except sqlalchemy.exc.IntegrityError as e:
            print(e)
            return False
        except Exception as e:
            print(str(e))
            return False

    def delete(self):
        with Session(engine) as session:
            session.delete(self)
            return session.commit()

    def save(self):
        with Session(engine) as session:
            self.modified = utcnow()
            session.add(self)
            session.commit()
            session.refresh(self)
            return self

    @classmethod
    def load(cls, id):
        with Session(engine) as session:
            return session.get(cls, id)

    @classmethod
    def load_by_filter(cls, *conditions, column=None, values=None, limit=None):
        with Session(engine) as session:
            statement = select(cls)
            for condition in conditions:
                statement = statement.where(condition)
            if column is not None and values is not None:
                statement = statement.where(column.in_(values))
            results = session.exec(
                statement.limit(limit).order_by(cls.id.desc())
            )
            return results.all()
