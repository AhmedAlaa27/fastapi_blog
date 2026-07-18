from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: EmailStr = Field(max_length=120)


class UserCreate(UserBase):
    password: str = Field(min_length=6, max_length=100)


class UserUpdate(UserBase):
    username: str | None = Field(default=None, min_length=1, max_length=50)  # type: ignore[assignment]
    email: EmailStr | None = Field(default=None, max_length=120)  # type: ignore[assignment]


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    image_file: str | None
    image_path: str


class UserPrivate(UserPublic):
    email: EmailStr
