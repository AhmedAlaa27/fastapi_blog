from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Post, User
from app.repositories.post_repository import PostRepository
from app.repositories.user_repository import UserRepository
from app.schemas.post import PaginatedPostsResponse, PostCreate, PostResponse, PostUpdate

post_repository = PostRepository()
user_repository = UserRepository()


async def list_posts(db: AsyncSession, skip: int, limit: int) -> PaginatedPostsResponse:
    total = await post_repository.count_all(db)
    posts = await post_repository.list_paginated(db, skip, limit)
    has_more = skip + len(posts) < total

    return PaginatedPostsResponse(
        posts=[PostResponse.model_validate(post) for post in posts],
        total=total,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )


async def list_user_posts(
    db: AsyncSession, user_id: int, skip: int, limit: int
) -> PaginatedPostsResponse:
    user = await user_repository.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

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


async def get_post(db: AsyncSession, post_id: int) -> Post:
    post = await post_repository.get_by_id(db, post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )
    return post


async def create_post(db: AsyncSession, data: PostCreate, current_user: User) -> Post:
    new_post = Post(
        title=data.title,
        content=data.content,
        user_id=current_user.id,
    )
    post_repository.create(db, new_post)
    await db.commit()
    await db.refresh(new_post, attribute_names=["author"])
    return new_post


async def _get_owned_post(db: AsyncSession, post_id: int, current_user: User) -> Post:
    post = await post_repository.get_by_id(db, post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this post",
        )
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
    return post


async def delete_post(db: AsyncSession, post_id: int, current_user: User) -> None:
    post = await post_repository.get_by_id(db, post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this post",
        )

    await post_repository.delete(db, post)
    await db.commit()
