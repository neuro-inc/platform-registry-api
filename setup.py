from setuptools import setup, find_packages


install_requires = (
    'aiodns==1.1.1',
    'aiohttp==3.4.4',
    'cchardet==2.1.1',
    'dataclasses==0.6',  # backport from 3.7 stdlib
)

setup(
    name='platform-registry-api',
    version='0.0.1b1',
    url='https://github.com/neuromation/platform-registry-api',
    packages=find_packages(),
    install_requires=install_requires,
    entry_points={
        'console_scripts': 'platform-registry-api=platform_registry_api.api:main'
    },
)
