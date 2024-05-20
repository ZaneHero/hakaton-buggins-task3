from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base


class Groups(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str]

    def __str__(self):
        return f"Group {self.name}"