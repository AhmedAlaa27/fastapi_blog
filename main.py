from fastapi import FastAPI, Request, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from schemas import PostCreate, PostResponse

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

posts: list[dict] = [
    {
        "id": 1,
        "author": "Alice Johnson",
        "title": "Getting Started with FastAPI",
        "content": "FastAPI is a modern Python web framework that makes it easy to build APIs. In this post, I'll walk through the basics of setting up your first project and creating endpoints.",
        "date_posted": "2024-01-15",
    },
    {
        "id": 2,
        "author": "Bob Smith",
        "title": "Advanced Async Patterns in Python",
        "content": "Async/await syntax has revolutionized how we write concurrent code in Python. Let's explore some real-world patterns and best practices for handling I/O-bound operations efficiently.",
        "date_posted": "2024-01-16",
    },
    {
        "id": 3,
        "author": "Charlie Davis",
        "title": "Database Design Best Practices",
        "content": "Designing a scalable database schema is crucial for long-term project success. We'll discuss normalization, indexing strategies, and query optimization techniques that every developer should know.",
        "date_posted": "2024-01-17",
    },
]


@app.get("/", include_in_schema=False, name="home")
@app.get("/posts", include_in_schema=False, name="posts")
def home(request: Request):
    return templates.TemplateResponse(
        request,
        "home.html",
        {"posts": posts, "title": "Home"},
    )


@app.get("/posts/{post_id}", include_in_schema=False, name="post_detail")
def view_post(request: Request, post_id: int):
    for post in posts:
        if post.get("id") == post_id:
            title = post.get("title", "Post Detail")[:50]
            return templates.TemplateResponse(
                request,
                "post.html",
                {"post": post, "title": title},
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")


@app.get("/api/posts", response_model=list[PostResponse])
def get_posts():
    return posts


@app.post(
    "/api/posts",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_post(post: PostCreate):
    new_post = post.model_dump()
    new_post["id"] = max((p["id"] for p in posts), default=0) + 1
    new_post["date_posted"] = "2024-01-18"  # Simulated date
    posts.append(new_post)
    return new_post


@app.get("/api/posts/{post_id}", response_model=PostResponse)
def get_post(post_id: int):
    for post in posts:
        if post.get("id") == post_id:
            return post
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")


## StarletteHTTPException Handler
@app.exception_handler(StarletteHTTPException)
def general_http_exception_handler(request: Request, exception: StarletteHTTPException):
    message = (
        exception.detail
        if exception.detail
        else "An error occurred. Please check your request and try again."
    )

    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exception.status_code,
            content={"detail": message},
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": exception.status_code,
            "title": exception.status_code,
            "message": message,
        },
        status_code=exception.status_code,
    )


### RequestValidationError Handler
@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exception: RequestValidationError):
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": exception.errors()},
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "title": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "message": "Invalid request. Please check your input and try again.",
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
