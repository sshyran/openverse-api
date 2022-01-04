"""
Contains SQLAlchemy models corresponding to Django ORM models. These models are
excluded from migrations.
"""

from sqlalchemy import Column, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base


Base = declarative_base()


class Image(Base):
    """Managed by Django model ``Image``"""

    __tablename__ = "image"

    id = Column(Integer, primary_key=True)
    identifier = Column(UUID)
    source = Column(String)
    provider = Column(String)
    title = Column(String)