#!/bin/bash
# Stop execution on first error
set -e
# Show commands as they are executed
set -x

# Prevent interaction from apt with the user
export DEBIAN_FRONTEND=noninteractive

# We update the apt-get cache
apt-get update

# Install method HTTPS
apt-get install -y apt-transport-https

# Add repository for ElasticSearch
wget -qO - https://packages.elastic.co/GPG-KEY-elasticsearch | apt-key add -
echo "deb https://packages.elastic.co/elasticsearch/2.x/debian stable main" | tee -a /etc/apt/sources.list.d/elasticsearch-2.x.list
# Add repository for OpenJDK 8
wget -qO - https://adoptopenjdk.jfrog.io/adoptopenjdk/api/gpg/key/public | sudo apt-key add -
echo "deb https://adoptopenjdk.jfrog.io/adoptopenjdk/deb buster main" | sudo tee /etc/apt/sources.list.d/adoptopenjdk.list


# We update the apt-get cache
apt-get update
apt-get install -y build-essential curl screen libxml2-dev libxslt1-dev gettext \
        libjpeg-dev liblapack-dev gfortran libopenblas-dev libmagickwand-dev \
        default-jre-headless libffi-dev \
        pwgen git
apt-get install -y pdftk
# Make imagemagick read pdf
sudo sed -i 's/<policy domain="coder" rights="none" pattern="PDF" \/>/<policy domain="coder" rights="read" pattern="PDF" \/>/' /etc/ImageMagick-6/policy.xml
# We install Python
apt-get install -y python3 python3-dev python3-venv
# We install PostgreSQL now
apt-get install -y postgresql postgresql-server-dev-all postgresql-client
# We install ElasticSearch now
# ES 2.4.x needs Java 8
apt-get install -y adoptopenjdk-8-hotspot-jre
# Then we must set this as default JRE
sudo update-java-alternatives -s adoptopenjdk-8-hotspot-jre-amd64
# Ready for ES
apt-get install -y elasticsearch
# We install moreutils
apt-get install -y moreutils
# We install required geo libraries
# https://docs.djangoproject.com/en/2.1/ref/contrib/gis/install/geolibs/
apt-get install -y binutils libproj-dev gdal-bin
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
python3 -m venv /home/vagrant/.vm_venv

# Update pip and setuptools
/home/vagrant/.vm_venv/bin/pip install --upgrade pip setuptools

# We install dependencies in the virtualenv
req_files=(requirements.txt requirements-dev.txt)
for req in "${req_files[@]}"
do
        /home/vagrant/.vm_venv/bin/pip install -r "/dissemin/$req"
done

# Configure secrets

if [ -f "/dissemin/dissemin/settings/secret.py" ]
then
        echo "A secret file already exists, moved to secret.py.user"
        mv /dissemin/dissemin/settings/secret.py /dissemin/dissemin/settings/secret.py.user
fi

cp /dissemin/dissemin/settings/secret_template.py /dissemin/dissemin/settings/secret.py
sed -i -e "s/^SECRET_KEY = .*/SECRET_KEY = '$(pwgen -s 60 -1)'/" /dissemin/dissemin/settings/secret.py
sed -i -e "s/^        'PASSWORD': .*/        'PASSWORD': '${DB_PASSWORD}',/" /dissemin/dissemin/settings/secret.py

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
  . /home/vagrant/.vm_venv/bin/activate
}
activate_venv
python /dissemin/manage.py migrate
python /dissemin/manage.py loaddata /dissemin/papers/fixtures/test_dump.json
python /dissemin/manage.py update_index

# We run a new tmux session containing the Dissemin development server.
_SNAME=Django

sudo -u vagrant -H bash <<EOF
cat >> /home/vagrant/.bash_profile <<LOL
source /home/vagrant/.vm_venv/bin/activate
LOL

tmux start-server
tmux new-session -d -s $_SNAME
# Remain on exit
tmux set-option -t $_SNAME set-remain-on-exit on
# Django development server
tmux new-window -t $_SNAME -n django -c '/dissemin' -d '/home/vagrant/.vm_venv/bin/python /dissemin/manage.py runserver 0.0.0.0:8080'
# Celery backend
tmux new-window -t $_SNAME -n celery -c '/dissemin' -d 'PYTHONPATH=/dissemin /home/vagrant/.vm_venv/bin/celery --app=dissemin.celery:app worker -B -l INFO'
# Super user prompt
tmux new-window -t $_SNAME -n superuser -c '/dissemin' -d '/home/vagrant/.vm_venv/bin/python /dissemin/manage.py createsuperuser'
EOF
