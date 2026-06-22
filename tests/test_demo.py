from fastapi import FastAPI
from fastapi.testclient import TestClient

demo_app = FastAPI()


@demo_app.get("/")
def demo_home():
    return {"message": "Hello, World!"}


client = TestClient(demo_app)


def test_demo_home():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, World!"}
