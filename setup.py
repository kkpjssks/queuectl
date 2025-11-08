from setuptools import setup, find_packages

setup(
    name="queuectl",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click>=8.0",
    ],
    entry_points={
        "console_scripts": [
            "queuectl = queuectl.cli:cli",
        ],
    },
    author="KSHITIZ GUPTA",
    author_email="f20220057@pilani.bits-pilani.ac.in",
    description="A CLI background job queue system.",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="httpsG://github.com/kkpjssks/queuectl", 
)