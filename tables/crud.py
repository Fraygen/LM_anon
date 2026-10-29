from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, desc, delete
from tables.database import AsyncSessionLocal, Announcement, Reaction, User

async def save_user_to_db(user_id: int):
    async with AsyncSessionLocal() as session:
        existing = await session.get(User, user_id)
        if not existing:
            session.add(User(user_id=user_id))
            await session.commit()

async def get_all_users():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.user_id))
        return result.scalars().all()

async def add_announcement(author_id: int, author_username: str | None, author_fullname: str | None, text: str | None, photo_file_id: str | None):
    async with AsyncSessionLocal() as session:
        clean_text = text.strip() if text else ""
        new_announcement = Announcement(
            author_id=author_id,
            author_username=author_username,
            author_fullname=author_fullname,
            text=clean_text,
            photo_file_id=photo_file_id,
            status="published"
        )
        session.add(new_announcement)
        await session.commit()
        await session.refresh(new_announcement)
        return new_announcement

async def get_unread_count_since(last_seen_id: int) -> int:
    async with AsyncSessionLocal() as session:
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=3)
        stmt = select(func.count(Announcement.id)).where(
            Announcement.status == 'published',
            Announcement.created_at >= cutoff_time,
            Announcement.id > last_seen_id
        )
        return (await session.execute(stmt)).scalar_one()

async def increment_view(announcement_id: int):
    async with AsyncSessionLocal() as session:
        announcement = await session.get(Announcement, announcement_id)
        if announcement:
            announcement.views_count += 1
            await session.commit()
            await session.refresh(announcement)
            return announcement.views_count
        return 0

async def delete_announcement(announcement_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(Reaction).where(Reaction.announcement_id == announcement_id))
            stmt = delete(Announcement).where(Announcement.id == announcement_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0
        except Exception as e:
            await session.rollback()
            print(f"Ошибка при удалении анонса: {e}")
            return False

async def handle_reaction(announcement_id: int, user_id: int, value: str):
    async with AsyncSessionLocal() as session:
        announcement = await session.get(Announcement, announcement_id)
        if not announcement:
            return None

        stmt = select(Reaction).where(Reaction.announcement_id == announcement_id, Reaction.user_id == user_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            if existing.value == value:
                if value == 'like':
                    announcement.likes_count = max(0, announcement.likes_count - 1)
                else:
                    announcement.dislikes_count = max(0, announcement.dislikes_count - 1)
                await session.delete(existing)
            else:
                if value == 'like':
                    announcement.likes_count += 1
                    announcement.dislikes_count = max(0, announcement.dislikes_count - 1)
                else:
                    announcement.dislikes_count += 1
                    announcement.likes_count = max(0, announcement.likes_count - 1)
                existing.value = value
        else:
            new_react = Reaction(announcement_id=announcement_id, user_id=user_id, value=value)
            session.add(new_react)
            if value == 'like':
                announcement.likes_count += 1
            else:
                announcement.dislikes_count += 1

        await session.commit()
        await session.refresh(announcement)
        return {"likes": announcement.likes_count, "dislikes": announcement.dislikes_count}

async def get_feed_page(announcement_id: int | None = None):
    async with AsyncSessionLocal() as session:
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=3)

        if announcement_id is None:
            stmt = (
                select(Announcement)
                .where(Announcement.status == 'published', Announcement.created_at >= cutoff_time)
                .order_by(desc(Announcement.id))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
        else:
            stmt = (
                select(Announcement)
                .where(
                    Announcement.id == announcement_id,
                    Announcement.status == 'published',
                    Announcement.created_at >= cutoff_time
                )
            )
            row = (await session.execute(stmt)).scalar_one_or_none()

        if not row:
            return None

        total_stmt = (
            select(func.count(Announcement.id))
            .where(Announcement.status == 'published', Announcement.created_at >= cutoff_time)
        )
        total = (await session.execute(total_stmt)).scalar_one()

        pos_stmt = (
            select(func.count(Announcement.id))
            .where(
                Announcement.status == 'published',
                Announcement.created_at >= cutoff_time,
                Announcement.id >= row.id
            )
        )
        position = (await session.execute(pos_stmt)).scalar_one()

        newer_stmt = (
            select(Announcement.id)
            .where(
                Announcement.status == 'published',
                Announcement.created_at >= cutoff_time,
                Announcement.id > row.id
            )
            .order_by(Announcement.id.asc())
            .limit(1)
        )
        newer_id = (await session.execute(newer_stmt)).scalar_one_or_none()

        older_stmt = (
            select(Announcement.id)
            .where(
                Announcement.status == 'published',
                Announcement.created_at >= cutoff_time,
                Announcement.id < row.id
            )
            .order_by(Announcement.id.desc())
            .limit(1)
        )
        older_id = (await session.execute(older_stmt)).scalar_one_or_none()

        return {
            "item": row,
            "position": position,
            "total": total,
            "newer_id": newer_id,
            "older_id": older_id
        }