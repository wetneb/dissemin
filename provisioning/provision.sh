#!/bin/bash

# We update the apt-get cache
apt-get update

# Install method HTTPS
apt-get install -y apt-transport-https

# Add new repositories for services

# ElasticSearch
wget -qO - https://packages.elastic.co/GPG-KEY-elasticsearch | apt-key add -
echo "deb https://packages.elastic.co/elasticsearch/2.x/debian stable main" | tee -a /etc/apt/sources.list.d/elasticsearch-2.x.list

# We update the apt-get cache
apt-get update
apt-get install -y build-essential curl screen libxml2-dev libxslt1-dev gettext \
        libjpeg-dev liblapack-dev gfortran libopenblas-dev libmagickwand-dev \
        default-jre-headless libffi-dev \
        pwgen git

# We install Python
apt-get install -y python python-dev python-virtualenv virtualenv
# We install PostgreSQL now
apt-get install -y postgresql postgresql-server-dev-all postgresql-client
# We install ElasticSearch now
apt-get install -y elasticsearch
# We setup a Dissemin user
DB_PASSWORD=$(pwgen -s 60 -1)
sudo -u postgres -H bash <<EOF
psql -c "CREATE USER dissemin WITH PASSWORD '${DB_PASSWORD}';"
psql -c "ALTER USER dissemin CREATEDB;"
createdb --owner dissemin dissemin
EOF
# We install Redis
apt-get install -y redis-server

# We restart all services and enable all services
systemctl daemon-reload

systemctl enable postgresql
systemctl restart postgresql

systemctl enable redis-server
systemctl restart redis-server

systemctl enable elasticsearch
systemctl restart elasticsearch

# We install some dev tools (tmux and vim)
apt-get install -y tmux vim-nox
# We create a virtualenv for Dissemin
virtualenv /dissemin/.vm_venv --no-site-packages -p $(which python2.7)
# We install dependencies in the virtualenv
req_files=(requirements.txt requirements-dev.txt)

/dissemin/.vm_venv/bin/pip install --upgrade setuptools
for req in "${req_files[@]}"
do
        /dissemin/.vm_venv/bin/pip install -r "/dissemin/$req"
done

# Configure secrets

if [ -f "/dissemin/dissemin/settings/secret.py" ]
then
        echo "A secret file already exists, moved to secret.py.user"
        mv /dissemin/dissemin/settings/secret.py /dissemin/dissemin/settings/secret.py.user
fi

cat <<EOF > /dissemin/dissemin/settings/secret.py
# coding: utf-8

### Security key ###
# This is used by django to generate various things (mainly for 
# authentication). Just pick a fairly random string and keep it
# secret.
SECRET_KEY = "$(pwgen -s 60 -1)"

# Database
# https://docs.djangoproject.com/en/1.6/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'dissemin',
        'USER': 'dissemin',
        'PASSWORD': '${DB_PASSWORD}',
        'HOST': 'localhost'
    }
}

# Redis (if you use it)
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = ''

### Emailing settings ###
# These are used to send messages to the researchers.
# This is still a very experimental feature. We recommend you leave these
# settings as they are for now.
EMAIL_HOST = ''
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
EMAIL_USE_TLS = True

### API keys ###
# These keys are used to communicate with various interfaces. See
# http://dissemin.readthedocs.org/en/latest/apikeys.html 

# RoMEO API KEY
# Used to fetch publisher policies. Get one at
# http://www.sherpa.ac.uk/romeo/apiregistry.php
ROMEO_API_KEY = None

# Proaixy API key
# Used to fetch paper metadata. Get one by asking developers@dissem.in
PROAIXY_API_KEY = None
EOF

if [ -f "/dissemin/dissemin/settings/__init__.py" ]
then
        echo "__init__.py file already exists in settings, moved to __init__.py.user"
        mv /dissemin/dissemin/settings/__init__.py /dissemin/dissemin/settings/__init__.py.user
fi

if [ -f "/dissemin/dissemin/settings/search_engine.py" ]
then
        echo "Search engine settings already exists, moved to search_engine.py.user"
        mv /dissemin/dissemin/settings/search_engine.py /dissemin/dissemin/settings/search_engine.py.user
fi

cat <<EOF > /dissemin/dissemin/settings/search_engine.py
### Backend for Haystack

import os

# Haystack
HAYSTACK_CONNECTIONS = {
    'default': {
        'ENGINE': 'haystack.backends.elasticsearch_backend.ElasticsearchSearchEngine',
        'INDEX_NAME': 'haystack',
        'URL': 'http://127.0.0.1:9200/'
    },
}
EOF

echo 'from .dev import *' > /dissemin/dissemin/settings/__init__.py

function activate_venv () {
  . /dissemin/.vm_venv/bin/activate
}
activate_venv
python /dissemin/manage.py migrate
python /dissemin/manage.py loaddata /dissemin/papers/fixtures/test_dump.json
python /dissemin/manage.py update_index

# We run a new tmux session containing the Dissemin development server.
_SNAME=Django

sudo -u vagrant -H bash <<EOF
cat >> /home/vagrant/.bash_profile <<LOL
source /dissemin/.vm_venv/bin/activate
LOL

tmux start-server
tmux new-session -d -s $_SNAME
# Remain on exit
tmux set-option -t $_SNAME set-remain-on-exit on
# Django development server
tmux new-window -t $_SNAME -n django -c '/dissemin' -d '/dissemin/.vm_venv/bin/python /dissemin/manage.py runserver 0.0.0.0:8080'
# Celery backend
tmux new-window -t $_SNAME -n celery -c '/dissemin' -d '/dissemin/.vm_venv/bin/celery --app=dissemin.celery:app worker -B -l INFO'
# Super user prompt
tmux new-window -t $_SNAME -n superuser -c '/dissemin' -d '/dissemin/.vm_venv/bin/python /dissemin/manage.py createsuperuser'
EOF
