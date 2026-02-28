from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

posts: list[dict] = [
    {
        "id": 1,
        "author": "Alice",
        "title": "First Post",
        "content": "This is my first blog post.",
        "date_posted": "2024-01-15",
    },
    {
        "id": 2,
        "author": "Bob",
        "title": "Second Post",
        "content": "Learning FastAPI is fun!",
        "date_posted": "2024-01-16",
    },
    {
        "id": 3,
        "author": "Charlie",
        "title": "Third Post",
        "content": "Building APIs with Python.",
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


@app.get("/api/posts")
def get_posts():
    return posts
