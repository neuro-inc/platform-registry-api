from setuptools import find_packages, setup


install_requires = (
    "aiodns==2.0.0",
    "aiohttp==3.6.2",
    "aiohttp-remotes==0.1.2",
    "cchardet==2.1.6",
    "iso8601==0.1.12",
    "neuro_auth_client==19.10.5",
    "uvloop==0.14.0",
    "aiobotocore==1.0.2",
    "platform-logging==0.3",
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
