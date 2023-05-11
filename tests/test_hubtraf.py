async def test_login(user, hub_url):
    success = await user.login()
    assert success
    home_url = hub_url / "hub/home"
    r = await user.session.get(home_url)
    assert r.url == home_url
    assert r.status == 200


async def test_full(user):
    success = await user.login()
    assert success
    assert await user.ensure_server_simulate(timeout=120, spawn_refresh_time=5)
    assert await user.start_kernel()
    await user.assert_code_output("5 * 4", "20", 5, 5)


def test_dummy():
    # weirdly the async fixtures don't work
    # unless there's at least one sync test somewhere
    pass
