import re
import time
from keycloak import KeycloakOpenID
from html.parser import HTMLParser
from hubtraf.user import OperationError

def parse_kc_login_page(content):
    kc_regex = re.compile(u'\s+<form id="kc-form-login" .* action="(.*)" method="(.*)">')
    match = kc_regex.search(content)
    if match:
        return HTMLParser().unescape(match.group(1))
    return None

async def login_keycloak(session, hub_url, log, username, password):
    start_time = time.monotonic()
    url = hub_url / 'hub/oauth_login'

    # Get Keycloak OAuth URL
    try:
        resp = await session.get(url, allow_redirects=True)
    except Exception as e:
        log.msg('Login: Failed with exception {}'.format(repr(e)), action='login', phase='failed', duration=time.monotonic() - start_time)
        raise OperationError()
    if resp.status != 200:
        log.msg('Login: Failed with response {}'.format(str(resp)), action='login', phase='failed', duration=time.monotonic() - start_time)
        raise OperationError()
    
    content = await resp.text()
    kc_url = parse_kc_login_page(content)

    # Login by Keycloak 
    try:
        payload='username={username}&password={password}'.format(username=username, password=password)
        resp = await session.post(kc_url, allow_redirects=False, data=payload, headers={'content-type': 'application/x-www-form-urlencoded'})
    except Exception as e:
        log.msg('Keycloak Login: Failed with exception {}'.format(repr(e)), action='login', phase='failed', duration=time.monotonic() - start_time)
        raise OperationError()
    if resp.status != 302:
        log.msg('Keycloak Login: Failed with response {}'.format(str(resp)), action='login', phase='failed', duration=time.monotonic() - start_time)
        raise OperationError()

    # Redirect to Hub
    hub_oauth_url = resp.headers['Location']
    try:
        resp = await session.get(hub_oauth_url)
    except Exception as e:
        log.msg('Hub OAuth Login: Failed with exception {}'.format(repr(e)), action='login', phase='failed', duration=time.monotonic() - start_time)
        raise OperationError()

    log.msg('Keycloak Login: Complete', action='login', phase='pass', duration=time.monotonic() - start_time)