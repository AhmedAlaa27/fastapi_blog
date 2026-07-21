from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, require_permission
from app.core.config import settings
from app.db.session import get_db
from app.schemas.post import PaginatedPostsResponse, PostCreate, PostResponse, PostUpdate
from app.services import audit_service, post_service

router = APIRouter()


@router.get("", response_model=PaginatedPostsResponse)
async def get_posts(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: Annotated[int, Query(ge=0, description="Number of posts to skip")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Items per page")
    ] = settings.posts_per_page,
    search: Annotated[
        str | None, Query(description="Search title, content, and author username")
    ] = None,
    author: Annotated[
        int | None, Query(ge=1, description="Filter by author user_id")
    ] = None,
    created_after: Annotated[
        datetime | None,
        Query(description="Only posts created after this datetime (ISO 8601)"),
    ] = None,
    created_before: Annotated[
        datetime | None,
        Query(description="Only posts created before this datetime (ISO 8601)"),
    ] = None,
    sort: Annotated[
        str,
        Query(description="Sort field: date_posted, title, likes; prefix '-' for descending"),
    ] = "-date_posted",
):
    return await post_service.list_posts(
        db,
        skip,
        limit,
        search=search,
        author=author,
        created_after=created_after,
        created_before=created_before,
        sort=sort,
    )


@router.post(
    "",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("posts:create"))],
)
async def create_post(
    request: Request,
    post: PostCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    new_post = await post_service.create_post(db, post, current_user)
    await audit_service.log_event(
        db,
        user_id=current_user.id,
        action="create",
        resource="post",
        resource_id=new_post.id,
        request=request,
    )
    return new_post


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(post_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    return await post_service.get_post(db, post_id)


@router.put("/{post_id}", response_model=PostResponse)
async def update_post_full(
    request: Request,
    post_id: int,
    post_data: PostCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    post = await post_service.update_post_full(db, post_id, post_data, current_user)
    await audit_service.log_event(
        db,
        user_id=current_user.id,
        action="update",
        resource="post",
        resource_id=post_id,
        request=request,
    )
    return post


@router.patch("/{post_id}", response_model=PostResponse)
async def update_post_partial(
    request: Request,
    post_id: int,
    post_data: PostUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    post = await post_service.update_post_partial(db, post_id, post_data, current_user)
    await audit_service.log_event(
        db,
        user_id=current_user.id,
        action="update",
        resource="post",
        resource_id=post_id,
        request=request,
    )
    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    request: Request,
    post_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await post_service.delete_post(db, post_id, current_user)
    await audit_service.log_event(
        db,
        user_id=current_user.id,
        action="delete",
        resource="post",
        resource_id=post_id,
        request=request,
    )
