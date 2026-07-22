from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.exceptions.base import BadRequestError, PermissionDeniedError
from app.exceptions.posts import PostNotFoundError
from app.exceptions.users import UserNotFoundError
from app.infrastructure.cache.keys import post_detail_key, post_list_key, post_list_pattern
from app.infrastructure.cache.redis_cache_service import RedisCacheService
from app.models import Post, User
from app.repositories.post_repository import PostRepository
from app.repositories.user_repository import UserRepository
from app.schemas.post import PaginatedPostsResponse, PostCreate, PostResponse, PostUpdate
from app.services.cache_service import CacheService

post_repository = PostRepository()
user_repository = UserRepository()
cache_service: CacheService = RedisCacheService()


async def list_posts(
    db: AsyncSession,
    skip: int,
    limit: int,
    search: str | None = None,
    author: int | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    sort: str = "-date_posted",
) -> PaginatedPostsResponse:
    cache_key = post_list_key(skip, limit, search, author, created_after, created_before, sort)
    cached = await cache_service.get(cache_key)
    if cached is not None:
        return PaginatedPostsResponse.model_validate(cached)

    field_name = sort.lstrip("-")
    if field_name not in PostRepository.SORT_FIELDS:
        raise BadRequestError(
            f"Invalid sort field '{field_name}'. Valid options: "
            f"{', '.join(PostRepository.SORT_FIELDS)}"
        )

    search = search.strip() if search else None

    posts, total = await post_repository.search_posts(
        db,
        search=search,
        author=author,
        created_after=created_after,
        created_before=created_before,
        sort=sort,
        skip=skip,
        limit=limit,
    )
    has_more = skip + len(posts) < total

    response = PaginatedPostsResponse(
        posts=[PostResponse.model_validate(post) for post in posts],
        total=total,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )
    await cache_service.set(cache_key, response.model_dump(mode="json"), ttl=settings.cache_default_ttl)
    return response


async def list_user_posts(
    db: AsyncSession, user_id: int, skip: int, limit: int
) -> PaginatedPostsResponse:
    user = await user_repository.get_by_id(db, user_id)
    if not user:
        raise UserNotFoundError()

    total = await post_repository.count_by_user(db, user_id)
    posts = await post_repository.list_by_user_paginated(db, user_id, skip, limit)
    has_more = skip + len(posts) < total

    return PaginatedPostsResponse(
        posts=[PostResponse.model_validate(post) for post in posts],
        total=total,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )


async def get_post(db: AsyncSession, post_id: int) -> PostResponse:
    cache_key = post_detail_key(post_id)
    cached = await cache_service.get(cache_key)
    if cached is not None:
        return PostResponse.model_validate(cached)

    post = await post_repository.get_by_id(db, post_id)
    if not post:
        raise PostNotFoundError()

    response = PostResponse.model_validate(post)
    await cache_service.set(cache_key, response.model_dump(mode="json"), ttl=settings.cache_default_ttl)
    return response


async def create_post(db: AsyncSession, data: PostCreate, current_user: User) -> Post:
    new_post = Post(
        title=data.title,
        content=data.content,
        user_id=current_user.id,
    )
    post_repository.create(db, new_post)
    await db.commit()
    await db.refresh(new_post, attribute_names=["author"])
    await cache_service.delete_pattern(post_list_pattern())
    return new_post


def _authorize_post_mutation(current_user: User, post: Post, permission: str) -> None:
    is_owner = post.user_id == current_user.id
    has_override = permission in {
        p.name for role in current_user.roles for p in role.permissions
    }
    if not is_owner and not has_override:
        raise PermissionDeniedError("Not authorized to perform this action on this post")


async def _get_owned_post(db: AsyncSession, post_id: int, current_user: User) -> Post:
    post = await post_repository.get_by_id(db, post_id)
    if not post:
        raise PostNotFoundError()

    _authorize_post_mutation(current_user, post, "posts:update")
    return post


async def update_post_full(
    db: AsyncSession, post_id: int, data: PostCreate, current_user: User
) -> Post:
    post = await _get_owned_post(db, post_id, current_user)

    post.title = data.title
    post.content = data.content
    post.user_id = current_user.id

    await db.commit()
    await db.refresh(post, attribute_names=["author"])
    await cache_service.delete(post_detail_key(post_id))
    await cache_service.delete_pattern(post_list_pattern())
    return post


async def update_post_partial(
    db: AsyncSession, post_id: int, data: PostUpdate, current_user: User
) -> Post:
    post = await _get_owned_post(db, post_id, current_user)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(post, field, value)

    await db.commit()
    await db.refresh(post, attribute_names=["author"])
    await cache_service.delete(post_detail_key(post_id))
    await cache_service.delete_pattern(post_list_pattern())
    return post


async def delete_post(db: AsyncSession, post_id: int, current_user: User) -> None:
    post = await post_repository.get_by_id(db, post_id)
    if not post:
        raise PostNotFoundError()

    _authorize_post_mutation(current_user, post, "posts:delete")

    await post_repository.delete(db, post)
    await db.commit()
    await cache_service.delete(post_detail_key(post_id))
    await cache_service.delete_pattern(post_list_pattern())
