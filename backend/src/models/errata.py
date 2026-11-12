from sqlalchemy import Text,JSON,ForeignKey,Integer,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from ..config.database import Base
from ..utils.clock import now
class WindowErrataBatch(Base):
    __tablename__="window_errata_batches"
    id:Mapped[int]=mapped_column(primary_key=True)
    __table_args__=(UniqueConstraint("study_id","batch_no"),)
    study_id:Mapped[int]=mapped_column(ForeignKey("archive_studies.id"))
    batch_no:Mapped[str]=mapped_column(Text)
    source_version:Mapped[int]=mapped_column(Integer)
    status:Mapped[str]=mapped_column(Text)
    total:Mapped[int]=mapped_column(Integer,default=0)
    applied:Mapped[int]=mapped_column(Integer,default=0)
    skipped:Mapped[int]=mapped_column(Integer,default=0)
    rejected:Mapped[int]=mapped_column(Integer,default=0)
    details:Mapped[list]=mapped_column(JSON,default=list)
    error:Mapped[str]=mapped_column(Text,default="")
    actor:Mapped[str]=mapped_column(Text)
    created_at:Mapped[str]=mapped_column(default=now)
