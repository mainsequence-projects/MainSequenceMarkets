"""Application-owned contract; physical creation is performed by its provider."""

from sqlalchemy import MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from metatables import PlatformManagedMetaTable, sqlalchemy_naming_convention


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class Note(PlatformManagedMetaTable, Base):
    __tablename__ = 'metatables_local_example__note'
    __metatable_namespace__ = 'metatables_local_example'
    __metatable_identifier__ = 'metatables_local_example.note'
    __metatable_description__ = 'Notes written through the local API example.'

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    message: Mapped[str] = mapped_column(String(200))
