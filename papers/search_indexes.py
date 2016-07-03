from .models import Paper
from haystack import indexes


class PaperIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, model_attr='title')
    pubdate = indexes.DateField(model_attr='pubdate')
    combined_status = indexes.CharField(model_attr='combined_status')
    doctype = indexes.CharField(model_attr='doctype')
    visible = indexes.BooleanField(model_attr='visible')
    oa_status = indexes.CharField(model_attr='oa_status')
    availability = indexes.CharField()

    #: Names of the authors
    authors_full = indexes.MultiValueField()
    authors_last = indexes.MultiValueField()

    #: IDs of researchers
    researchers = indexes.MultiValueField()

    #: IDs of departments of researchers
    departments = indexes.MultiValueField()

    #: ID of publisher
    publisher = indexes.IntegerField(null=True)

    #: ID of journal
    journal = indexes.IntegerField(null=True)

    def get_model(self):
        return Paper

    def prepare_authors_full(self, obj):
        return [a['name']['full'] for a in obj.authors_list]

    def prepare_authors_last(self, obj):
        return [a['name']['last'] for a in obj.authors_list]

    def prepare_availability(self, obj):
        return 'OK' if obj.pdf_url else 'NOK'

    def prepare_researchers(self, obj):
        return [r.id for r in obj.researchers.all()]

    def prepare_departments(self, obj):
        return list(set([r.department_id for r in obj.researchers.all()]))

    def prepare_publisher(self, obj):
        oairecord = obj.oairecords.filter(journal__isnull=False).first()
        return getattr(getattr(oairecord, 'publisher', None), 'id', None)

    def prepare_journal(self, obj):
        oairecord = obj.oairecords.filter(journal__isnull=False).first()
        return getattr(getattr(oairecord, 'journal', None), 'id', None)
