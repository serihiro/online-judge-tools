#!/usr/bin/env python3
from setuptools import setup, find_packages

with open('readme.md') as fh:
    readme = fh.read()
with open('LICENSE') as fh:
    license = fh.read()

setup(
    name='online-judge-tools',
    version='0.1.0',
    description='Tools for online-judge services',
    install_requires=[
        'requests',
        'beautifulsoup4',
        'colorama',
    ],
    long_description=readme,
    author='Kimiyuki Onaka',
    author_email='kimiyuki95@gmail.com',
    url='https://github.com/kmyk/online-judge-tools',
    license=license,
    packages=find_packages(exclude=( 'tests', 'docs' )),
    scripts=[ 'oj' ],
)
