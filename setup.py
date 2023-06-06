from setuptools import find_packages, setup

setup(
    name='hubtraf',
    version='0.1',
    url='https://github.com/yuvipanda/hubtraf',
    license='3-clause BSD',
    author='YuviPanda',
    author_email='yuvipanda@gmail.com',
    packages=find_packages(),
    install_requires=['aiohttp', 'structlog', 'oauthlib', 'yarl', 'colorama'],
    entry_points={
        'console_scripts': [
            'hubtraf-simulate = hubtraf.simulate:main',
            'hubtraf-check = hubtraf.check:main'
        ],
    },
)
