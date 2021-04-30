# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

with open('requirements.txt') as f:
	install_requires = f.read().strip().split('\n')

# get version from __version__ variable in rest_migrate/__init__.py
from rest_migrate import __version__ as version

setup(
	name='rest_migrate',
	version=version,
	description='Migrate data from a rest endpoint',
	author='CaseSolved',
	author_email='support@casesolved.co.uk',
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
