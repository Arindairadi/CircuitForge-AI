import datetime as dt
from sqlalchemy import ForeignKey, String, Text, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base


def now(): return dt.datetime.now(dt.UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Token(Base):
    __tablename__ = "tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    versions: Mapped[list["ProjectVersion"]] = relationship(cascade="all, delete-orphan", order_by="ProjectVersion.number")


class ProjectVersion(Base):
    __tablename__ = "project_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    circuit_json: Mapped[str] = mapped_column(Text)
    results_json: Mapped[str] = mapped_column(Text, default="{}")  # verification/simulation records for this version
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class ProjectMember(Base):
    __tablename__ = "project_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # viewer | editor


class AuditEvent(Base):  # project_id is a plain integer so history survives project deletion
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed
    result_json: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class CustomComponent(Base):  # user-entered library parts (private to the owner); never presented as verified
    __tablename__ = "custom_components"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(300))
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    package: Mapped[str | None] = mapped_column(String(60), nullable=True)
    datasheet_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    specs_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class PartAssignment(Base):  # real part chosen by the user for one reference designator
    __tablename__ = "part_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(10))
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mpn: Mapped[str | None] = mapped_column(String(100), nullable=True)
    datasheet_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    price: Mapped[str | None] = mapped_column(String(40), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str] = mapped_column(String(300), default="")
    entered_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Datasheet(Base):
    __tablename__ = "datasheets"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    stored_name: Mapped[str] = mapped_column(String(64))  # server-generated; the user's filename is display-only
    display_name: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
