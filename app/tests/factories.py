import secrets
from datetime import UTC, datetime, timedelta

import factory
from factory import Faker

from app.core.security import hash_password
from app.models import Post, RefreshToken, User


class UserFactory(factory.Factory):
    class Meta:
        model = User

    username = Faker("user_name")
    email = Faker("email")
    password_hash = factory.LazyFunction(lambda: hash_password("testpassword123"))
    email_verified = True


class PostFactory(factory.Factory):
    class Meta:
        model = Post

    title = Faker("sentence", nb_words=6)
    content = Faker("paragraph")
    likes = 0


class RefreshTokenFactory(factory.Factory):
    class Meta:
        model = RefreshToken

    token_hash = factory.LazyFunction(lambda: secrets.token_hex(32))
    revoked = False
    expires_at = factory.LazyFunction(lambda: datetime.now(UTC) + timedelta(days=30))
