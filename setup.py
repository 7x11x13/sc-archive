from setuptools import setup, find_packages

setup(
    name="sc-archive",
    version="1.0.3",
    packages=find_packages(),
    author="7x11x13",
    install_requires=[
        "discord-webhook",
        "pika",
        "psycopg2",
        "scdl>=2.9.5",
        "soundcloud-v2>=1.3.7",
        "sqlalchemy>=1.4.0,<2.0.0",
    ],
    python_requires=">=3.7",
    entry_points={"console_scripts": ["sc-archive-run = sc_archive.archive:run"]},
)
