import asyncio
import random
import time
import uuid
from enum import Enum

import aiohttp
import colorama
import structlog
from yarl import URL

logger = structlog.get_logger()


class User:
    class States(Enum):
        CLEAR = 1
        LOGGED_IN = 2
        SERVER_STARTED = 3
        KERNEL_STARTED = 4

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.close()

    def __init__(self, username, hub_url, login_handler):
        """
        A simulated JupyterHub user.

        username - name of the user.
        hub_url - base url of the hub.
        login_handler - a awaitable callable that will be passed the following parameters:
                            username
                            session (aiohttp session object)
                            log (structlog log object)
                            hub_url (yarl URL object)

                        It should 'log in' the user with whatever requests it needs to
                        perform. If no uncaught exception is thrown, login is considered
                        a success.

                        Usually a partial of a generic function is passed in here.
        """
        self.username = username
        self.hub_url = URL(hub_url)

        self.state = User.States.CLEAR
        self.notebook_url = self.hub_url / "user" / self.username

        self.log = logger.bind(username=username)
        self.login_handler = login_handler
        self.headers = {'Referer': str(self.hub_url / 'hub/')}

    def success(self, kind, **kwargs):
        kwargs_pretty = " ".join([f"{k}:{v}" for k, v in kwargs.items()])
        print(
            f'{colorama.Fore.GREEN}Success:{colorama.Style.RESET_ALL}',
            kind,
            self.username,
            kwargs_pretty,
        )

    def failure(self, kind, **kwargs):
        kwargs_pretty = " ".join([f"{k}:{v}" for k, v in kwargs.items()])
        print(
            f'{colorama.Fore.RED}Failure:{colorama.Style.RESET_ALL}',
            kind,
            self.username,
            kwargs_pretty,
        )

    def debug(self, kind, **kwargs):
        kwargs_pretty = " ".join([f"{k}:{v}" for k, v in kwargs.items()])
        print(
            f'{colorama.Fore.YELLOW}Debug:{colorama.Style.RESET_ALL}',
            kind,
            self.username,
            kwargs_pretty,
        )

    async def login(self):
        """
        Log in to the JupyterHub.

        We only log in, and try to not start the server itself. This
        makes our testing code simpler, but we need to be aware of the fact this
        might cause differences vs how users normally use this.
        """
        # We only log in if we haven't done anything already!
        assert self.state == User.States.CLEAR

        start_time = time.monotonic()
        logged_in = await self.login_handler(
            log=self.log,
            hub_url=self.hub_url,
            session=self.session,
            username=self.username,
        )
        if not logged_in:
            return False
        hub_cookie = self.session.cookie_jar.filter_cookies(self.hub_url).get(
            'hub', None
        )
        if hub_cookie:
            self.log = self.log.bind(hub=hub_cookie.value)
        self.success('login', duration=time.monotonic() - start_time)
        self.state = User.States.LOGGED_IN
        return True

    async def ensure_server_api(self, api_token, timeout=300, spawn_refresh_time=30):
        api_url = self.hub_url / 'hub/api'
        self.headers['Authorization'] = f'token {api_token}'

        async def server_running():
            async with self.session.get(
                api_url / 'users' / self.username, headers=self.headers
            ) as resp:
                userinfo = await resp.json()
                server = userinfo.get('servers', {}).get('', {})
                self.debug(
                    'server-start',
                    phase='waiting',
                    ready=server.get('ready'),
                    pending=server.get('pending'),
                )
                return server.get('ready', False)

        self.debug('server-start', phase='start')
        start_time = time.monotonic()

        async with self.session.post(
            api_url / 'users' / self.username / 'server', headers=self.headers
        ) as resp:
            if resp.status == 201:
                # Server created
                # FIXME: Verify this server is actually up
                self.success('server-start', duration=time.monotonic() - start_time)
                self.state = User.States.SERVER_STARTED
                return True
            elif resp.status == 202:
                # Server start request received, not necessarily started
                # FIXME: Verify somehow?
                self.debug('server-start', phase='waiting')
                while not (await server_running()):
                    await asyncio.sleep(0.5)
                self.success('server-start', duration=time.monotonic() - start_time)
                self.state = User.States.SERVER_STARTED
                return True
            elif resp.status == 400:
                body = await resp.json()
                if body['message'] == f'{self.username} is already running':
                    self.state = User.States.SERVER_STARTED
                    return True
            print(await resp.json())
            print(resp.request_info)
            return False

    async def ensure_server_simulate(self, timeout=300, spawn_refresh_time=30):
        assert self.state == User.States.LOGGED_IN

        start_time = time.monotonic()
        self.debug('server-start', phase='start')
        i = 0
        while True:
            i += 1
            self.debug('server-start', phase='attempt-start', attempt=i + 1)
            try:
                resp = await self.session.get(self.hub_url / 'hub/spawn')
            except Exception as e:
                self.debug(
                    'server-start',
                    exception=str(e),
                    attempt=i + 1,
                    phase='attempt-failed',
                    duration=time.monotonic() - start_time,
                )
                continue
            # Check if paths match, ignoring query string (primarily, redirects=N), fragments
            target_url_tree = self.notebook_url / 'tree'
            if (
                resp.url.scheme == target_url_tree.scheme
                and resp.url.host == target_url_tree.host
                and resp.url.path == target_url_tree.path
            ):
                self.success(
                    'server-start',
                    phase='complete',
                    attempt=i + 1,
                    duration=time.monotonic() - start_time,
                )
                break
            target_url_lab = self.notebook_url / 'lab'
            if (
                resp.url.scheme == target_url_lab.scheme
                and resp.url.host == target_url_lab.host
                and resp.url.path == target_url_lab.path
            ):
                self.success(
                    'server-start',
                    phase='complete',
                    attempt=i + 1,
                    duration=time.monotonic() - start_time,
                )
                break
            if time.monotonic() - start_time >= timeout:
                self.failure(
                    'server-start',
                    phase='failed',
                    duration=time.monotonic() - start_time,
                    reason='timeout',
                )
                return False
            # Always log retries, so we can count 'in-progress' actions
            self.debug(
                'server-start',
                resp=str(resp),
                phase='attempt-complete',
                duration=time.monotonic() - start_time,
                attempt=i + 1,
            )
            # FIXME: Add jitter?
            await asyncio.sleep(random.uniform(0, spawn_refresh_time))

        self.state = User.States.SERVER_STARTED
        self.headers['X-XSRFToken'] = self.xsrf_token
        return True

    async def stop_server(self):
        assert self.state == User.States.SERVER_STARTED
        self.debug('server-stop', phase='start')
        start_time = time.monotonic()
        try:
            resp = await self.session.delete(
                self.hub_url / 'hub/api/users' / self.username / 'server',
                headers=self.headers,
            )
        except Exception as e:
            self.failure(
                'server-stop', exception=str(e), duration=time.monotonic() - start_time
            )
            return False
        if resp.status != 202 and resp.status != 204:
            self.failure(
                'server-stop',
                exception=str(resp),
                duration=time.monotonic() - start_time,
            )
            return False
        self.success('server-stop', duration=time.monotonic() - start_time)
        self.state = User.States.LOGGED_IN
        return True

    async def start_kernel(self):
        assert self.state == User.States.SERVER_STARTED

        self.debug('kernel-start', phase='start')
        start_time = time.monotonic()

        try:
            resp = await self.session.post(
                self.notebook_url / 'api/kernels', headers=self.headers
            )
        except Exception as e:
            self.failure(
                'kernel-start', exception=str(e), duration=time.monotonic() - start_time
            )
            return False

        if resp.status != 201:
            self.failure(
                'kernel-start',
                exception=str(resp),
                duration=time.monotonic() - start_time,
            )
            return False
        self.kernel_id = (await resp.json())['id']
        self.success('kernel-start', duration=time.monotonic() - start_time)
        self.state = User.States.KERNEL_STARTED
        return True

    @property
    def xsrf_token(self):
        # cookie filter needs trailing slash for path prefix
        notebook_cookies = self.session.cookie_jar.filter_cookies(
            str(self.notebook_url) + "/"
        )
        assert '_xsrf' in notebook_cookies
        xsrf_token = notebook_cookies['_xsrf'].value
        return xsrf_token

    async def stop_kernel(self):
        assert self.state == User.States.KERNEL_STARTED

        self.debug('kernel-stop', phase='start')
        start_time = time.monotonic()
        try:
            resp = await self.session.delete(
                self.notebook_url / 'api/kernels' / self.kernel_id, headers=self.headers
            )
        except Exception as e:
            self.failure(
                'kernel-stop', exception=str(e), duration=time.monotonic() - start_time
            )
            return False

        if resp.status != 204:
            self.failure(
                'kernel-stop',
                exception=str(resp),
                duration=time.monotonic() - start_time,
            )
            return False

        self.success('kernel-stop', duration=time.monotonic() - start_time)
        self.state = User.States.SERVER_STARTED
        return True

    def request_execute_code(self, msg_id, code):
        return {
            "header": {
                "msg_id": msg_id,
                "username": self.username,
                "msg_type": "execute_request",
                "version": "5.2",
            },
            "metadata": {},
            "content": {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": True,
                "stop_on_error": True,
            },
            "buffers": [],
            "parent_header": {},
            "channel": "shell",
        }

    async def assert_code_output(
        self, code, output, execute_timeout, repeat_time_seconds=None
    ):
        channel_url = self.notebook_url / 'api/kernels' / self.kernel_id / 'channels'
        self.debug('kernel-connect', phase='start')
        try:
            async with self.session.ws_connect(channel_url, headers=self.headers) as ws:
                self.debug('kernel-connect', phase='complete')
                start_time = time.monotonic()
                iteration = 0
                self.debug('code-execute', phase='start')
                while True:
                    exec_start_time = time.monotonic()
                    iteration += 1
                    msg_id = str(uuid.uuid4())
                    await ws.send_json(self.request_execute_code(msg_id, code))
                    async for msg_text in ws:
                        if msg_text.type != aiohttp.WSMsgType.TEXT:
                            self.failure(
                                'code-execute',
                                iteration=iteration,
                                message=str(msg_text),
                                duration=time.monotonic() - exec_start_time,
                            )
                            return False

                        msg = msg_text.json()

                        if (
                            'parent_header' in msg
                            and msg['parent_header'].get('msg_id') == msg_id
                        ):
                            # These are responses to our request
                            if msg['channel'] == 'iopub':
                                response = None
                                if msg['msg_type'] == 'execute_result':
                                    response = msg['content']['data']['text/plain']
                                elif msg['msg_type'] == 'stream':
                                    response = msg['content']['text']
                                if response:
                                    assert response == output
                                    duration = time.monotonic() - exec_start_time
                                    break
                    if repeat_time_seconds:
                        if time.monotonic() - start_time >= repeat_time_seconds:
                            break
                        else:
                            # Sleep a random amount of time between 0 and 1s, so we aren't busylooping
                            await asyncio.sleep(random.uniform(0, 1))
                            continue
                    else:
                        break

                self.success('code-execute', duration=duration, iteration=iteration)
                return True
        except Exception as e:
            self.failure('code-execute', exception=str(e))
            return False
