async def test_login(user, hub_url):
    success = await user.login()
    assert success
    home_url = hub_url / "hub/home"
    r = await user.session.get(home_url)
    assert r.url == home_url
    assert r.status_code == 200


async def test_full(user):
    success = await user.login()
    assert success
    await user.ensure_server_simulate()
    await user.start_kernel()
    await user.assert_code_output("5 * 4", "20", 5, 5)
