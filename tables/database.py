from sqlalchemy import String, BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from datetime import datetime
from settings import config

engine = create_async_engine(
    url=config.DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=10
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(BigInteger)
    author_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    author_fullname: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text: Mapped[str | None] = mapped_column(String(3000), nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="published")
    likes_count: Mapped[int] = mapped_column(default=0)
    dislikes_count: Mapped[int] = mapped_column(default=0)
    views_count: Mapped[int] = mapped_column(default=0)

class Reaction(Base):
    __tablename__ = "reactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    announcement_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[str] = mapped_column(String(10))

class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())