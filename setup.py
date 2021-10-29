from setuptools import setup, find_packages

import sc_archive

setup(
    name='sc-archive',
    version='1.0.1',
    packages=find_packages(),
    author='7x11x13',
    install_requires=[
        'appdirs',
        'pika',
        'psycopg2',
        'requests',
        'soundcloud-v2',
        'sqlalchemy'
    ],
    python_requires='>=3.8',
    entry_points={
        'console_scripts': [
            'sc-archive-run = sc_archive.archive:run',
            'sc-archive-run-watcher = sc_archive.watcher_webhook:run',
            'sc-archive-set-auth = sc_archive.archive:set_auth',
            'sc-archive-set-client-id = sc_archive.archive:set_client_id'
        ]
    }
)