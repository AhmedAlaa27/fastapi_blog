from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    async def save_profile_image(self, content: bytes) -> str: ...

    @abstractmethod
    def delete_profile_image(self, filename: str | None) -> None: ...
