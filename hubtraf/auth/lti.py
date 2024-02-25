import time
import uuid

from oauthlib.oauth1.rfc5849 import signature

from hubtraf.user import OperationError


async def lti_login_data(
    session,
    log,
    hub_url,
    username,
    consumer_key,
    consumer_secret,
    launch_url,
    extra_args={},
):
    """
    Log in username with LTI info to hub_url

    log is used to emit timing and status information.
    """
    args = {
        'oauth_consumer_key': consumer_key,
        'oauth_timestamp': str(time.time()),
        'oauth_nonce': str(uuid.uuid4()),
        'user_id': username,
    }

    args.update(extra_args)

    base_string = signature.construct_base_string(
        'POST',
        signature.normalize_base_string_uri(launch_url),
        signature.normalize_parameters(
            signature.collect_parameters(body=args, headers={})
        ),
    )

    args['oauth_signature'] = signature.sign_hmac_sha1(
        base_string, consumer_secret, None
    )

    url = hub_url / 'lti/launch'

    try:
        resp = await session.post(url, data=args, allow_redirects=False)
    except Exception as e:
        log.msg(
            f'Login: Failed with exception {repr(e)}',
            action='login',
            phase='failed',
            duration=time.monotonic() - start_time,
        )
        raise OperationError()
    if resp.status != 302:
        log.msg(
            f'Login: Failed with response {str(resp)}',
            action='login',
            phase='failed',
            duration=time.monotonic() - start_time,
        )
        raise OperationError()
    return args
