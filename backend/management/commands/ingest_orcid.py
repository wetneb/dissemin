from django.core.management.base import BaseCommand
from backend.orcid import OrcidPaperSource

class Command(BaseCommand):
    help = 'Ingest an ORCID dump'

    def add_arguments(self, parser):
        parser.add_argument('activities', help='ORCID activities tar.gz dump.')
        parser.add_argument('summaries_dir', help='ORCID summaries extracted dump.')

    def handle(self, *args, **options):
        o = OrcidPaperSource()
        o.bulk_import(options['summaries_dir'], options['activities'])
