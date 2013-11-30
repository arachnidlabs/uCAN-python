#!/usr/bin/env python

from distutils.core import setup

setup(name='uCAN',
      version='1.0',
      description='Python uCAN library',
      author='Nick Johnson',
      author_email='nick@notdot.net',
      url='http://www.arachnidlabs.com/',
      license='MIT',
      packages=['uCAN'],
      dependency_links=['https://bitbucket.org/hardbyte/python-can/get/default.tar.gz'],
      install_requires=['python-can', 'enum34', 'bitstring'],
      test_suite='uCAN.tests')
