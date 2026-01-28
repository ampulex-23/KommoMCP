"""SQLAlchemy database models."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class TimestampMixin:
    """Mixin for timestamp fields."""
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    synced_at = Column(DateTime, server_default=func.now())


class KommoMixin(TimestampMixin):
    """Mixin for Kommo entity timestamps."""
    kommo_created_at = Column(DateTime)
    kommo_updated_at = Column(DateTime)


# Association tables
lead_contacts = Table(
    'lead_contacts',
    Base.metadata,
    Column('lead_id', BigInteger, ForeignKey('leads.id'), primary_key=True),
    Column('contact_id', BigInteger, ForeignKey('contacts.id'), primary_key=True),
    Column('is_main', Boolean, default=False),
)

lead_companies = Table(
    'lead_companies',
    Base.metadata,
    Column('lead_id', BigInteger, ForeignKey('leads.id'), primary_key=True),
    Column('company_id', BigInteger, ForeignKey('companies.id'), primary_key=True),
)

contact_companies = Table(
    'contact_companies',
    Base.metadata,
    Column('contact_id', BigInteger, ForeignKey('contacts.id'), primary_key=True),
    Column('company_id', BigInteger, ForeignKey('companies.id'), primary_key=True),
)


class UserDB(Base):
    """User model."""
    __tablename__ = 'users'

    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255))
    lang = Column(String(10), default='ru')
    rights = Column(JSONB, default={})
    is_active = Column(Boolean, default=True)
    synced_at = Column(DateTime, server_default=func.now())

    leads = relationship('LeadDB', back_populates='responsible_user')
    contacts = relationship('ContactDB', back_populates='responsible_user')
    companies = relationship('CompanyDB', back_populates='responsible_user')
    tasks = relationship('TaskDB', back_populates='responsible_user')


class PipelineDB(Base):
    """Pipeline model."""
    __tablename__ = 'pipelines'

    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    sort = Column(Integer, default=1)
    is_main = Column(Boolean, default=False)
    is_unsorted_on = Column(Boolean, default=True)
    is_archive = Column(Boolean, default=False)
    synced_at = Column(DateTime, server_default=func.now())

    stages = relationship('StageDB', back_populates='pipeline', order_by='StageDB.sort')
    leads = relationship('LeadDB', back_populates='pipeline')


class StageDB(Base):
    """Pipeline stage model."""
    __tablename__ = 'stages'

    id = Column(BigInteger, primary_key=True)
    pipeline_id = Column(BigInteger, ForeignKey('pipelines.id'), nullable=False)
    name = Column(String(255), nullable=False)
    sort = Column(Integer, default=0)
    color = Column(String(20), default='#fffeb2')
    is_editable = Column(Boolean, default=True)
    type = Column(Integer, default=0)  # 0=normal, 1=incoming, 2=won, 3=lost

    pipeline = relationship('PipelineDB', back_populates='stages')

    __table_args__ = (
        Index('ix_stages_pipeline', 'pipeline_id'),
    )


class LeadDB(Base, KommoMixin):
    """Lead model."""
    __tablename__ = 'leads'

    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    price = Column(Numeric(15, 2), default=0)
    responsible_user_id = Column(BigInteger, ForeignKey('users.id'))
    pipeline_id = Column(BigInteger, ForeignKey('pipelines.id'), nullable=False)
    status_id = Column(BigInteger, ForeignKey('stages.id'), nullable=False)
    loss_reason_id = Column(BigInteger)
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    closed_at = Column(DateTime)
    closest_task_at = Column(DateTime)
    is_deleted = Column(Boolean, default=False)
    custom_fields = Column(JSONB, default={})

    responsible_user = relationship('UserDB', back_populates='leads')
    pipeline = relationship('PipelineDB', back_populates='leads')
    status = relationship('StageDB')
    contacts = relationship('ContactDB', secondary=lead_contacts, back_populates='leads')
    companies = relationship('CompanyDB', secondary=lead_companies, back_populates='leads')
    # Note: tasks and notes relationships removed due to polymorphic entity_type
    # Use manual queries instead

    __table_args__ = (
        Index('ix_leads_pipeline_status', 'pipeline_id', 'status_id'),
        Index('ix_leads_responsible', 'responsible_user_id'),
        Index('ix_leads_created', 'kommo_created_at'),
        Index('ix_leads_closed', 'closed_at'),
    )


class ContactDB(Base, KommoMixin):
    """Contact model."""
    __tablename__ = 'contacts'

    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    responsible_user_id = Column(BigInteger, ForeignKey('users.id'))
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    closest_task_at = Column(DateTime)
    is_deleted = Column(Boolean, default=False)
    custom_fields = Column(JSONB, default={})

    responsible_user = relationship('UserDB', back_populates='contacts')
    leads = relationship('LeadDB', secondary=lead_contacts, back_populates='contacts')
    companies = relationship('CompanyDB', secondary=contact_companies, back_populates='contacts')

    __table_args__ = (
        Index('ix_contacts_responsible', 'responsible_user_id'),
        Index('ix_contacts_name', 'name'),
    )


class CompanyDB(Base, KommoMixin):
    """Company model."""
    __tablename__ = 'companies'

    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    responsible_user_id = Column(BigInteger, ForeignKey('users.id'))
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    closest_task_at = Column(DateTime)
    is_deleted = Column(Boolean, default=False)
    custom_fields = Column(JSONB, default={})

    responsible_user = relationship('UserDB', back_populates='companies')
    leads = relationship('LeadDB', secondary=lead_companies, back_populates='companies')
    contacts = relationship('ContactDB', secondary=contact_companies, back_populates='companies')

    __table_args__ = (
        Index('ix_companies_responsible', 'responsible_user_id'),
        Index('ix_companies_name', 'name'),
    )


class TaskDB(Base, KommoMixin):
    """Task model."""
    __tablename__ = 'tasks'

    id = Column(BigInteger, primary_key=True)
    text = Column(Text)  # Changed from String(1000) to Text for long task descriptions
    task_type_id = Column(Integer, default=1)
    entity_id = Column(BigInteger)
    entity_type = Column(String(50))
    responsible_user_id = Column(BigInteger, ForeignKey('users.id'))
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    is_completed = Column(Boolean, default=False)
    complete_till = Column(DateTime)
    duration = Column(Integer, default=0)
    result = Column(Text)  # Changed from String(1000) to Text

    responsible_user = relationship('UserDB', back_populates='tasks')
    # Note: relationship to lead removed due to polymorphic entity_type
    # Use manual queries instead: TaskDB.entity_type == 'leads' and TaskDB.entity_id == lead_id

    __table_args__ = (
        Index('ix_tasks_entity', 'entity_type', 'entity_id'),
        Index('ix_tasks_responsible', 'responsible_user_id'),
        Index('ix_tasks_complete_till', 'complete_till'),
        Index('ix_tasks_completed', 'is_completed'),
    )


class NoteDB(Base, KommoMixin):
    """Note model."""
    __tablename__ = 'notes'

    id = Column(BigInteger, primary_key=True)
    entity_id = Column(BigInteger, nullable=False)
    entity_type = Column(String(50), nullable=False)
    note_type = Column(Integer, default=4)
    text = Column(Text)
    params = Column(JSONB, default={})
    responsible_user_id = Column(BigInteger)
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)

    # Note: relationship to lead removed due to polymorphic entity_type
    # Use manual queries instead

    __table_args__ = (
        Index('ix_notes_entity', 'entity_type', 'entity_id'),
    )


class CustomFieldDB(Base):
    """Custom field metadata."""
    __tablename__ = 'custom_fields'

    id = Column(BigInteger, primary_key=True)
    entity_type = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(100))
    field_type = Column(String(50), nullable=False)
    sort = Column(Integer, default=0)
    is_api_only = Column(Boolean, default=False)
    enums = Column(JSONB, default=[])
    synced_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('ix_custom_fields_entity', 'entity_type'),
    )


class SyncStatusDB(Base):
    """Sync status tracking."""
    __tablename__ = 'sync_status'

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(50), nullable=False, unique=True)
    last_sync_at = Column(DateTime)
    last_sync_id = Column(BigInteger)
    records_count = Column(Integer, default=0)
    status = Column(String(20), default='idle')  # idle, running, completed, failed
    error_message = Column(Text)
