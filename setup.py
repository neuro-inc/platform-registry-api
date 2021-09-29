from setuptools import find_packages, setup


setup_requires = ("setuptools_scm",)

install_requires = (
    "aiodns==3.0.0",
    "aiohttp==3.7.4.post0",
    "aiohttp-remotes==1.0.0",
    "cchardet==2.1.7",
    "iso8601==0.1.16",
    "neuro_auth_client==21.9.13.1",
    # uvloop 0.15.x has a bug and doesn't work with AWS registry + Kaniko
    # cache: https://github.com/neuro-inc/platform-registry-api/issues/343
    # uvloop 0.15.3 definitely has the bug, but upcoming versions may
    # have it fixed. See the issue above for testing instructions.
    "uvloop==0.14.0",
    "aiobotocore==1.4.1",
    "neuro-logging==21.9",
    "trafaret==2.1.0",
    "aiozipkin==1.1.0",
    "yarl==1.6.3",
    "sentry-sdk==1.4.2",
)

setup(
    name="platform-registry-api",
    url="https://github.com/neuro-inc/platform-registry-api",
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
