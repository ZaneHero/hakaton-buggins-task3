from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings

DATABASE_URL = settings.DATABASE_URL
engine = create_async_engine(DATABASE_URL)
async_sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass