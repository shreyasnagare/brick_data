from setuptools import setup, find_packages
from pkg_resources import parse_requirements

__author__ = 'Jason Koh'
__version__ = '0.0.1'

install_reqs = parse_requirements(open('requirements.txt'))
#with open('requirements.txt') as fp:
#        install_requires = fp.read()
reqs = [ir.name for ir in install_reqs]

setup(
    name = 'brick_data',
    version = __version__,
    packages = find_packages(),
    description = 'A wrapper of Timeseries DBs',
    install_requires = reqs,
    #install_requires=install_requires
)

