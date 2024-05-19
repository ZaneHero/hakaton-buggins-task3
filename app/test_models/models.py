from sqlalchemy.orm import mapped_column, relationship, Mapped
from app.database import Base


class TestTable(Base):
    __tablename__ = "testtable"

    testcolumn: Mapped[str] = mapped_column(primary_key=True)
