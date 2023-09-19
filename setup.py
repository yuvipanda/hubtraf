from setuptools import find_packages, setup

setup(
    name='hubtraf',
    version='1.0.0.dev',
    url='https://github.com/yuvipanda/hubtraf',
    license='3-clause BSD',
    author='YuviPanda',
    author_email='yuvipanda@gmail.com',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'hubtraf-simulate = hubtraf.simulate:main',
            'hubtraf-check = hubtraf.check:main'
        ],
    },
    install_requires=[
        "aiohttp",
        "structlog",
        "oauthlib",
        "yarl",
        "colorama",
    ],
    extras_require={
        "test": [
            "ipykernel",
            "jupyter-server",
            "jupyterlab",
            "jupyterhub",
            "pytest",
            "pytest-asyncio",
            "pytest-cov",
            "pytest-jupyterhub",
        ],
    },
)
