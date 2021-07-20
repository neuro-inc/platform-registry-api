from setuptools import find_packages, setup


setup_requires = ("setuptools_scm",)

install_requires = (
    "aiodns==3.0.0",
    "aiohttp==3.7.4.post0",
    "aiohttp-remotes==1.0.0",
    "cchardet==2.1.7",
    "iso8601==0.1.16",
    "neuro_auth_client==21.5.17",
    "uvloop==0.15.3",
    "aiobotocore==1.3.3",
    "platform-logging==21.5.27",
    "trafaret==2.1.0",
    "aiozipkin==1.1.0",
    "yarl==1.6.3",
    "sentry-sdk==1.3.0",
)

setup(
    name="platform-registry-api",
    url="https://github.com/neuromation/platform-registry-api",
    use_scm_version={
        "git_describe_command": "git describe --dirty --tags --long --match v*.*.*",
    },
    packages=find_packages(),
    setup_requires=setup_requires,
    install_requires=install_requires,
    python_requires=">=3.8",
    entry_points={
        "console_scripts": "platform-registry-api=platform_registry_api.api:main"
    },
)
