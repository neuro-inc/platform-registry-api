from setuptools import find_packages, setup


install_requires = (
    "aiodns==1.1.1",
    "aiohttp==3.4.4",
    "aiohttp-remotes==0.1.2",
    "async-exit-stack==1.0.1",  # backport from 3.7 stdlib
    "cchardet==2.1.1",
    "dataclasses==0.6",  # backport from 3.7 stdlib
    "iso8601==0.1.12",
    "neuro_auth_client==1.0.5",
    "uvloop==0.12.2",
)

setup(
    name="platform-registry-api",
    version="0.0.1b1",
    url="https://github.com/neuromation/platform-registry-api",
    packages=find_packages(),
    install_requires=install_requires,
    entry_points={
        "console_scripts": "platform-registry-api=platform_registry_api.api:main"
    },
)
