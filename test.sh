#!/bin/bash
source .virtualenv/bin/activate
export DJANGO_SETTINGS_MODULE="dissemin.testsettings"
python manage.py test --testrunner dissemin.fasttestrunner.FastTestRunner $@
