from setuptools import find_packages, setup


install_requires = (
    "aiodns==2.0.0",
    "aiohttp==3.6.1",
    "aiohttp-remotes==0.1.2",
    "async-exit-stack==1.0.1",  # backport from 3.7 stdlib
    "async-generator==1.10",
    "cchardet==2.1.4",
    "dataclasses==0.6",  # backport from 3.7 stdlib
    "iso8601==0.1.12",
    "neuro_auth_client==1.0.5",
    "uvloop==0.13.0",
    "aiobotocore==0.10.3",
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
