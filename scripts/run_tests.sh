#!/bin/sh

set -eu

flake8 pytempo/*py
nosetests --with-coverage --cover-package=pytempo
