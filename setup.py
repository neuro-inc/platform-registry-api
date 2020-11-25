from setuptools import find_packages, setup


install_requires = (
    "aiodns==2.0.0",
    "aiohttp==3.7.3",
    "aiohttp-remotes==1.0.0",
    "cchardet==2.1.7",
    "iso8601==0.1.13",
    "neuro_auth_client==19.10.5",
    "uvloop==0.14.0",
    "aiobotocore==1.1.2",
    "urllib3>=1.20,<1.27",  # botocore requirements
    "platform-logging==0.3",
    "trafaret==2.1.0",
    "aiozipkin==1.0.0",
    "yarl==1.6.3",
    "sentry-sdk==0.19.4",
)

setup(
    name="platform-registry-api",
    version="0.0.1b1",
    url="https://github.com/neuromation/platform-registry-api",
    packages=find_packages(),
    install_requires=install_requires,
    python_requires=">=3.7",
    entry_points={
        "console_scripts": "platform-registry-api=platform_registry_api.api:main"
    },
)
