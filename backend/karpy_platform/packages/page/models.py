from sqlalchemy import Boolean, Column, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from karpy_platform.core.base.models import BaseModel, SlugMixin, StatusMixin, SeoMixin


class Page(BaseModel, SlugMixin, StatusMixin, SeoMixin):
    """Botble-style CMS page model."""

    __tablename__ = "pages"

    name = Column(String(120), nullable=False)
    content = Column(Text, nullable=True)  # HTML from CKEditor + [shortcodes]
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    image = Column(String(500), nullable=True)
    template = Column(String(60), nullable=True, default="default")
    is_featured = Column(Boolean, default=False)
    description = Column(Text, nullable=True)

    user = relationship("User", lazy="selectin")

    def get_compiled_content(self) -> str:
        """Compile shortcodes in the content and return final HTML."""
        from karpy_platform.packages.shortcode.engine import shortcode_engine
        return shortcode_engine.compile(self.content)
