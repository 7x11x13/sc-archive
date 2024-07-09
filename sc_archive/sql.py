import datetime
from typing import Union

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


class SQLObj:
    @classmethod
    def from_dataclass(cls, dataclass):
        data = {}
        for column in cls.__table__.columns.keys():
            if hasattr(dataclass, column):
                data[column] = getattr(dataclass, column)
        return cls(**data)

    def update_from_dataclass(
        self, dataclass
    ) -> dict[str, tuple[Union[str, int], Union[str, int]]]:
        changes = {}
        for column in self.__table__.columns.keys():
            if column == "last_modified":
                continue
            if not hasattr(dataclass, column):
                continue
            old_value = getattr(self, column)
            new_value = getattr(dataclass, column)
            if old_value != new_value:
                if isinstance(old_value, datetime.datetime):
                    old_value = int(old_value.timestamp())
                    new_value = int(new_value.timestamp())
                changes[column] = (old_value, new_value)
            setattr(self, column, new_value)
        return changes

    def to_dict(self) -> dict[str, Union[str, int]]:
        data = {}
        for column in self.__table__.columns.keys():
            value = getattr(self, column)
            if isinstance(value, datetime.datetime):
                value = int(value.timestamp())
            data[column] = value
        return data


Base = declarative_base()


class SQLArtist(Base, SQLObj):
    __tablename__ = "artist"
    id = Column(Integer, primary_key=True)
    avatar_url = Column(String)
    last_modified = Column(DateTime, nullable=False)
    permalink_url = Column(String, nullable=False)
    username = Column(String, nullable=False)

    deleted = Column(DateTime)
    tracking = Column(Boolean, nullable=False, default=True)


class SQLTrack(Base, SQLObj):
    __tablename__ = "track"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("artist.id"), index=True)
    artwork_url = Column(String)
    description = Column(String)
    full_duration = Column(Integer, nullable=False)
    last_modified = Column(DateTime, nullable=False)
    permalink_url = Column(String, nullable=False)
    title = Column(String, nullable=False)
    downloadable = Column(Boolean, nullable=False)
    purchase_url = Column(String)

    deleted = Column(DateTime)
    file_path = Column(String)


def init_sql(url: str) -> sessionmaker:
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(engine)
