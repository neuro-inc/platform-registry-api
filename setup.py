from setuptools import find_packages, setup


setup_requires = ("setuptools_scm",)

install_requires = (
    "aiodns==2.0.0",
    "aiohttp==3.7.3",
    "aiohttp-remotes==1.0.0",
    "cchardet==2.1.7",
    "iso8601==0.1.14",
    "neuro_auth_client==21.1.6",
    "uvloop==0.15.1",
    "aiobotocore==1.2.1",
    "urllib3>=1.20,<1.27",  # botocore requirements
    "platform-logging==0.3",
    "trafaret==2.1.0",
    "aiozipkin==1.0.0",
    "yarl==1.6.3",
    "sentry-sdk==0.20.2",
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
    python_requires=">=3.7",
    entry_points={
        "console_scripts": "platform-registry-api=platform_registry_api.api:main"
    },
)
