import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool

from app.storage.base import Storage

APP_DIR = Path(__file__).resolve().parent.parent
PROFILE_PICS_DIR = APP_DIR / "media" / "profile_pics"


def _process_profile_image(content: bytes) -> str:
    with Image.open(BytesIO(content)) as original:
        img = ImageOps.exif_transpose(original)

        img = ImageOps.fit(img, (300, 300), method=Image.Resampling.LANCZOS)

        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        filename = f"{uuid.uuid4().hex}.jpg"
        filepath = PROFILE_PICS_DIR / filename

        PROFILE_PICS_DIR.mkdir(parents=True, exist_ok=True)

        img.save(filepath, "JPEG", quality=85, optimize=True)

    return filename


class LocalStorage(Storage):
    async def save_profile_image(self, content: bytes) -> str:
        return await run_in_threadpool(_process_profile_image, content)

    def delete_profile_image(self, filename: str | None) -> None:
        if filename is None:
            return

        filepath = PROFILE_PICS_DIR / filename
        if filepath.exists():
            filepath.unlink()


local_storage = LocalStorage()
