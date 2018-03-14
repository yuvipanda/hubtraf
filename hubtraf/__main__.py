from enum import Enum, auto
import aiohttp
import socket
import argparse
import uuid
import random
from yarl import URL
import asyncio
import async_timeout
import structlog
import time

logger = structlog.get_logger()

class OperationError(Exception):
    pass


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

    def __init__(self, username, password, hub_url):
        self.username = username
        self.password = password
        self.hub_url = URL(hub_url)

        self.state = User.States.CLEAR
        self.notebook_url = self.hub_url / 'user' / self.username

        self.log = logger.bind(
            username=username
        )

    async def login(self):
        """
        Log in to the JupyterHub with given credentials.

        We only log in, and try to not start the server itself. This
        makes our testing code simpler, but we need to be aware of the fact this
        might cause differences vs how users normally use this.
        """
        # We only log in if we haven't done anything already!
        assert self.state == User.States.CLEAR

        url = self.hub_url / 'hub/login'
        self.log.msg('Login: Starting', action='login', phase='start')
        start_time = time.monotonic()
        resp = await self.session.post(url, data={'username': self.username, 'password': self.password}, allow_redirects=False)
        if resp.status != 302:
            self.log.msg('Login: Failed {}'.format(str(await resp.text())), action='login', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()

        hub_cookie = self.session.cookie_jar.filter_cookies(self.hub_url).get('hub', None)
        if hub_cookie:
            self.log = self.log.bind(hub=hub_cookie.value)
        self.log.msg('Login: Complete', action='login', phase='complete', duration=time.monotonic() - start_time)
        self.state = User.States.LOGGED_IN

    async def ensure_server(self, timeout=300, server_start_maxwait=60):
        assert self.state == User.States.LOGGED_IN

        start_time = time.monotonic()
        self.log.msg(f'Server: Starting', action='server-start', phase='start')
        i = 0
        while True:
            i += 1
            self.log.msg(f'Server: Attmepting to Starting', action='server-start', phase='attempt-start', attempt=i + 1)
            resp = await self.session.get(self.hub_url / 'hub/spawn')
            if resp.url == self.notebook_url / 'tree':
                self.log.msg('Server: Started', action='server-start', phase='complete', attempt=i + 1, duration=time.monotonic() - start_time)
                break
            if time.monotonic() - start_time >= timeout:
                self.log.msg('Server: Failed', action='server-start', phase='failed', duration=time.monotonic() - start_time)
                raise OperationError()
            # Always log retries, so we can count 'in-progress' actions
            self.log.msg('Server: Retrying', action='server-start', phase='attempt-complete', duration=time.monotonic() - start_time, attempt=i + 1)
            # FIXME: Add jitter?
            await asyncio.sleep(max(i ^ 2, server_start_maxwait) + random.uniform(0, server_start_maxwait))
        
        self.state = User.States.SERVER_STARTED

    async def stop_server(self):
        assert self.state == User.States.SERVER_STARTED
        self.log.msg('Server: Stopping', action='server-stop', phase='start')
        start_time = time.monotonic()
        resp = await self.session.delete(
            self.hub_url / 'hub/api/users' / self.username / 'server',
            headers={'Referer': str(self.hub_url / 'hub/')}
        )
        if resp.status != 202 and resp.status != 204:
            self.log.msg('Server: Stop failed', action='server-stop', phase='failed', extra=str(resp), duration=time.monotonic() - start_time)
            raise OperationError()
        self.log.msg('Server: Stopped', action='server-stop', phase='complete', duration=time.monotonic() - start_time)
        self.state = User.States.LOGGED_IN

    async def start_kernel(self):
        assert self.state == User.States.SERVER_STARTED

        self.log.msg('Kernel: Starting', action='kernel-start', phase='start')
        start_time = time.monotonic()

        resp = await self.session.post(self.notebook_url / 'api/kernels', headers={'X-XSRFToken': self.xsrf_token})

        if resp.status != 201:
            self.log.msg('Kernel: Ststart failed', action='kernel-start', phase='failed', extra=str(resp), duration=time.monotonic() - start_time)
            raise OperationError()
        self.kernel_id = (await resp.json())['id']
        self.log.msg('Kernel: Started', action='kernel-start', phase='complete', duration=time.monotonic() - start_time)
        self.state = User.States.KERNEL_STARTED

    @property
    def xsrf_token(self):
        notebook_cookies = self.session.cookie_jar.filter_cookies(self.notebook_url)
        assert '_xsrf' in notebook_cookies
        xsrf_token = notebook_cookies['_xsrf'].value
        return xsrf_token

    async def stop_kernel(self):
        assert self.state == User.States.KERNEL_STARTED

        self.log.msg('Kernel: Stopping', action='kernel-stop', phase='start')
        start_time = time.monotonic()
        resp = await self.session.delete(self.notebook_url / 'api/kernels' / self.kernel_id, headers={'X-XSRFToken': self.xsrf_token})
        assert resp.status == 204
        self.log.msg('Kernel: Stopped', action='kernel-stop', phase='complete', duration=time.monotonic() - start_time)
        self.state = User.States.SERVER_STARTED

    def request_execute_code(self, msg_id, code):
        return {
            "header": {
                "msg_id": msg_id,
                "username": self.username,
                "msg_type": "execute_request",
                "version": "5.2"
            },
            "metadata": {},
            "content": {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": True,
                "stop_on_error": True
            },
            "buffers": [],
            "parent_header": {},
            "channel": "shell"
        }

    async def assert_code_output(self, code, output, execute_timeout, repeat_time_seconds):
        channel_url = self.notebook_url / 'api/kernels' / self.kernel_id / 'channels'
        self.log.msg('WS: Connecting', action='kernel-connect', phase='start')
        async with self.session.ws_connect(channel_url) as ws:
            self.log.msg('WS: Connected', action='kernel-connect', phase='complete')
            start_time = time.monotonic()
            iteration = 0
            while time.monotonic() - start_time < repeat_time_seconds:
                exec_start_time = time.monotonic()
                iteration += 1
                try:
                    async with async_timeout.timeout(execute_timeout):
                        msg_id = str(uuid.uuid4())
                        await ws.send_json(self.request_execute_code(msg_id, code))
                        async for msg_text in ws:
                            if msg_text.type != aiohttp.WSMsgType.TEXT:
                                self.log.msg('WS: Unexpected message type', action='code-execute', phase='failure', message_type=msg_text.type)
                                raise OperationError()

                            msg = msg_text.json()

                            if 'parent_header' in msg and msg['parent_header'].get('msg_id') == msg_id:
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
                                        if duration > 1:
                                            # Only print slow execution times
                                            self.log.msg('Code Execute: Slow', action='code-execute', phase='iteration', duration=duration, iteration=iteration)
                                        break
                except asyncio.TimeoutError:
                    self.log.msg(f'Code Execute: Timed Out', action='code-execute', phase='failure', duration=time.monotonic() - exec_start_time)
                    raise OperationError()
                # Sleep a random amount of time between 0 and 1s, so we aren't busylooping
                await asyncio.sleep(random.uniform(0, 1))
            self.log.msg('Code Execute: Complete', action='code-execute', phase='complete', iterations=iteration)




async def simulate_user(hub_url, username, password, delay_seconds, code_execute_seconds):
    await asyncio.sleep(delay_seconds)
    async with User(username, password, hub_url) as u:
        try:
            await u.login()
            await u.ensure_server()
            await u.start_kernel()
            await u.assert_code_output("5 * 4", "20", 5, code_execute_seconds)
        except OperationError:
            pass
        finally:
            if u.state == User.States.KERNEL_STARTED:
                await u.stop_kernel()
            if u.state == User.States.SERVER_STARTED:
                await u.stop_server()

def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'hub_url',
        help='Hub URL to send traffic to (without a trailing /)'
    )
    argparser.add_argument(
        'user_count',
        type=int,
        help='Number of users to simulate'
    )
    argparser.add_argument(
        '--user-prefix',
        default=socket.gethostname(),
        help='Prefix to use when generating user names'
    )
    argparser.add_argument(
        '--user-session-min-runtime',
        default=60,
        type=int,
        help='Min seconds user is active for'
    )
    argparser.add_argument(
        '--user-session-max-runtime',
        default=300,
        type=int,
        help='Max seconds user is active for'
    )
    argparser.add_argument(
        '--user-session-max-start-delay',
        default=60,
        type=int,
        help='Max seconds by which all users should have logged in'
    )
    argparser.add_argument(
        '--json',
        action='store_true',
        help='True if output should be JSON formatted'
    )
    args = argparser.parse_args()

    processors=[structlog.processors.TimeStamper(fmt="ISO")]

    if args.json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(processors=processors)

    awaits = []
    for i in range(args.user_count):
        awaits.append(simulate_user(
            args.hub_url,
            f'{args.user_prefix}-' + str(i),
            'hello',
            int(random.uniform(0, args.user_session_max_start_delay)),
            int(random.uniform(args.user_session_min_runtime, args.user_session_max_runtime))
        ))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(*awaits))
    

