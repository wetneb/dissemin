.. _page-dataingestion:

Data ingestion
============

A few API dumps and datasets are available and can be ingested into Dissemin.

ORCID
-----

`ORCID <https://orcid.org/>`_ provide dumps of their API. You should get in
contact with them to get access to the dumps. There are two complementary dumps
which can be imported into Dissemin:

- A dump of summaries, which are the API responses to the profiles queries.
  This one only contains summaries for all profiles.
- A dump of activities, which is a dump of all API responses to detailed
  activities of ORCID profiles (works, education, etc).

Both are a tar gz archive of XML files. The dump of summaries should be
extracted and converted to JSON using `the orcid conversion library
<https://github.com/ORCID/orcid-conversion-lib/>`_. Let us assume the resulting
JSON files are stored in ``/home/orcid/summaries``. The dump of activities
should be kept as a tar gz archive, let us assume it is sitting at
``/home/orcid/activities.tar.gz``.

The dumps can then be imported using ``python manage.py ingest_orcid
/home/orcid/activities.tar.gz /home/orcid/summaries``.
