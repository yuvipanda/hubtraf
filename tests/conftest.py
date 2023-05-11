from functools import partial

import pytest
from traitlets.config import Config
from yarl import URL

from hubtraf.auth.dummy import login_dummy
from hubtraf.user import User

pytest_plugins = "jupyterhub-spawners-plugin"


@pytest.fixture
async def app(hub_app):
    print(hub_app)
    config = Config()
    config.JupyterHub.authenticator_class = "dummy"
    config.JupyterHub.spawner_class = "simple"
    app = await hub_app(config=config)
    return app


@pytest.fixture
def hub_url(app):
    # aiohttp may exclude cookies on 127.0.0.1
    port = URL(app.bind_url).port
    return URL(f"http://localhost:{port}{app.base_url}")

user_counter = 0


@pytest.fixture
def username():
    global user_counter
    user_counter += 1
    return f"user-{user_counter}"


@pytest.fixture
async def user(username, app, hub_url):
    print("app", app)
    async with User(username, hub_url, partial(login_dummy, password="")) as u:
        yield u
