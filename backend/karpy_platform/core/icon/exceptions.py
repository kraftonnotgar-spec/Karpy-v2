class SvgNotFoundError(FileNotFoundError):
    @classmethod
    def missing(cls, name: str) -> "SvgNotFoundError":
        return cls(f'Icon "{name}" not found.')
