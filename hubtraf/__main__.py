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
from oauthlib.oauth1.rfc5849 import signature

logger = structlog.get_logger()

class OperationError(Exception):
    pass

# FIXME: HACK: This is terrible, refactor this to be something less crappy
LOGIN_TYPE = 'dummy'

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

    def lti_login_data(self, username, consumer_key, consumer_secret, launch_url, extra_args={}):
        args = {
            'oauth_consumer_key': consumer_key,
            'oauth_timestamp': str(time.time()),
            'oauth_nonce': str(uuid.uuid4()),
            'user_id': username
        }

        args.update(extra_args)

        base_string = signature.construct_base_string(
            'POST',
            signature.normalize_base_string_uri(launch_url),
            signature.normalize_parameters(
                signature.collect_parameters(body=args, headers={})
            )
        )

        args['oauth_signature'] = signature.sign_hmac_sha1(base_string, consumer_secret, None)
        return args


    async def login(self):
        """
        Log in to the JupyterHub with given credentials.

        We only log in, and try to not start the server itself. This
        makes our testing code simpler, but we need to be aware of the fact this
        might cause differences vs how users normally use this.
        """
        # We only log in if we haven't done anything already!
        assert self.state == User.States.CLEAR

        if LOGIN_TYPE == 'LTI':
            url = self.hub_url / 'hub/lti/launch'
            data = self.lti_login_data(self.username, 'thekey', 'thevalue', str(url), {'resource_link_id': self.username})
        else:
            url = self.hub_url / 'hub/login'
            data = {'username': self.username, 'password': self.password}
        self.log.msg('Login: Starting', action='login', phase='start')
        start_time = time.monotonic()
        try:
            resp = await self.session.post(url, data=data, allow_redirects=False)
        except Exception as e:
            self.log.msg('Login: Failed with exception {}'.format(repr(e)), action='login', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()
        if resp.status != 302:
            self.log.msg('Login: Failed with response {}'.format(str(resp)), action='login', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()

        hub_cookie = self.session.cookie_jar.filter_cookies(self.hub_url).get('hub', None)
        if hub_cookie:
            self.log = self.log.bind(hub=hub_cookie.value)
        self.log.msg('Login: Complete', action='login', phase='complete', duration=time.monotonic() - start_time)
        self.state = User.States.LOGGED_IN

    async def ensure_server(self, timeout=300, spawn_refresh_time=30):
        assert self.state == User.States.LOGGED_IN

        start_time = time.monotonic()
        self.log.msg(f'Server: Starting', action='server-start', phase='start')
        i = 0
        while True:
            i += 1
            self.log.msg(f'Server: Attmepting to Starting', action='server-start', phase='attempt-start', attempt=i + 1)
            try:
                resp = await self.session.get(self.hub_url / 'hub/spawn')
            except Exception as e:
                self.log.msg('Server: Failed {}'.format(str(e)), action='server-start', attempt=i + 1, phase='attempt-failed', duration=time.monotonic() - start_time)
                continue
            if resp.url == self.notebook_url / 'tree':
                self.log.msg('Server: Started', action='server-start', phase='complete', attempt=i + 1, duration=time.monotonic() - start_time)
                break
            if time.monotonic() - start_time >= timeout:
                self.log.msg('Server: Timeout', action='server-start', phase='failed', duration=time.monotonic() - start_time)
                raise OperationError()
            # Always log retries, so we can count 'in-progress' actions
            self.log.msg('Server: Retrying after response {}'.format(str(resp)), action='server-start', phase='attempt-complete', duration=time.monotonic() - start_time, attempt=i + 1)
            # FIXME: Add jitter?
            await asyncio.sleep(random.uniform(0, spawn_refresh_time))
        
        self.state = User.States.SERVER_STARTED

    async def stop_server(self):
        assert self.state == User.States.SERVER_STARTED
        self.log.msg('Server: Stopping', action='server-stop', phase='start')
        start_time = time.monotonic()
        try:
            resp = await self.session.delete(
                self.hub_url / 'hub/api/users' / self.username / 'server',
                headers={'Referer': str(self.hub_url / 'hub/')}
            )
        except Exception as e:
            self.log.msg('Server: Failed {}'.format(str(e)), action='server-stop', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()
        if resp.status != 202 and resp.status != 204:
            self.log.msg('Server: Stop failed', action='server-stop', phase='failed', extra=str(resp), duration=time.monotonic() - start_time)
            raise OperationError()
        self.log.msg('Server: Stopped', action='server-stop', phase='complete', duration=time.monotonic() - start_time)
        self.state = User.States.LOGGED_IN

    async def start_kernel(self):
        assert self.state == User.States.SERVER_STARTED

        self.log.msg('Kernel: Starting', action='kernel-start', phase='start')
        start_time = time.monotonic()

        try:
            resp = await self.session.post(self.notebook_url / 'api/kernels', headers={'X-XSRFToken': self.xsrf_token})
        except Exception as e:
            self.log.msg('Kernel: Start failed {}'.format(str(e)), action='kernel-start', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()

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
        try:
            resp = await self.session.delete(self.notebook_url / 'api/kernels' / self.kernel_id, headers={'X-XSRFToken': self.xsrf_token})
        except Exception as e:
            self.log.msg('Kernel:Failed Stopped {}'.format(str(e)), action='kernel-stop', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()

        if resp.status != 204:
            self.log.msg('Kernel:Failed Stopped {}'.format(str(resp)), action='kernel-stop', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()

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
        is_connected = False
        try:
            async with self.session.ws_connect(channel_url) as ws:
                is_connected = True
                self.log.msg('WS: Connected', action='kernel-connect', phase='complete')
                start_time = time.monotonic()
                iteration = 0
                self.log.msg('Code Execute: Started', action='code-execute', phase='start')
                while time.monotonic() - start_time < repeat_time_seconds:
                    exec_start_time = time.monotonic()
                    iteration += 1
                    msg_id = str(uuid.uuid4())
                    await ws.send_json(self.request_execute_code(msg_id, code))
                    async for msg_text in ws:
                        if msg_text.type != aiohttp.WSMsgType.TEXT:
                            self.log.msg(
                                'WS: Unexpected message type',
                                action='code-execute', phase='failure',
                                iteration=iteration,
                                message_type=msg_text.type, message=str(msg_text),
                                duration=time.monotonic() - exec_start_time
                            )
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
                                    break
                    # Sleep a random amount of time between 0 and 1s, so we aren't busylooping
                    await asyncio.sleep(random.uniform(0, 1))

                self.log.msg(
                    'Code Execute: complete',
                    action='code-execute', phase='complete',
                    duration=duration, iteration=iteration
                )
        except Exception as e:
            if type(e) is OperationError:
                raise
            if is_connected:
                self.log.msg('Code Execute: Failed {}'.format(str(e)), action='code-execute', phase='failure')
            else:
                self.log.msg('WS: Failed {}'.format(str(e)), action='kernel-connect', phase='failure')
            raise OperationError()


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
            try:
                if u.state == User.States.KERNEL_STARTED:
                    await u.stop_kernel()
            except OperationError:
                # We'll try to sto the server anyway
                pass
            try:
                if u.state == User.States.SERVER_STARTED:
                    await u.stop_server()
            except OperationError:
                # Nothing to do
                pass

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
    
if __name__ == '__main__':
    main()