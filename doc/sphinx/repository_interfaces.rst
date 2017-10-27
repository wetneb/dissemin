.. _page-repository_interfaces:

Writing an interface for a new repository
=========================================

Writing an interface for a new repository is very easy! Here is a quick
tutorial, whose only requirements
are some familiarity with Python, and have a running instance of Dissemin.

First, check that the repository you want to create an interface for
has an API that allows that.

In this tutorial we will write an interface for a DSpace repository, using
the `DSpace Demo <https://demo.dspace.org/>`_ as a test instance. This repository
supports the `SWORD <http://swordapp.org>`_ protocol, so let's write a SWORD
adapter for Dissemin.

Implementing the protocol
-------------------------

Protocol implementations are stored as submodules of the :mod:`deposit` module.
We start by creating a `sword` subdirectory within `deposit`, where we will
write all our Python code. Create an empty `__init__.py` file in our `deposit/sword`
directory to make sure it is a valid Python module.

To tell Dissemin how to interact with DSpace, we need to write an implementation
of that protocol. This has to be done in a dedicated file, `deposit/sword/protocol.py`, by creating a subclass of :class:`~deposit.protocol.RepositoryProtocol`::

   # this imports generic tools for our protocol implementation
   from deposit import protocol
   # this imports django's localization tools
   # it should sometimes be replaced by ugettext_lazy
   from django.utils.translation import ugettext as _

   class SwordProtocol(protocol.RepositoryProtocol):
        
        def submit_deposit(self, pdf, form):
            result = DepositResult()
            
            #########################################
            # Your paper-depositing code goes here! #
            #########################################


            # If the deposit succeeds, our deposit function should return
            # a DepositResult, with the following fields filled correctly:

            # A unique id provided by the repository (useful to modify
            # the deposit afterwards). The form is free, it only has to be a string.
            result.identifier = 'myrepo/deposit/12345'

            # The URL of the page of the paper on the repository,
            # and the URL of the full text
            result.splash_url = 'http://arxiv.org/abs/0809.3425'
            result.pdf_url = 'http://arxiv.org/pdf/0809.3425'

            return result

Let us see how we can access the data provided by Dissemin to perform the upload.
The paper to be deposited is available in `self.paper`, as a :class:`~papers.models.Paper` instance. This gives you access to all we know about the paper: title, authors,
sources, bibliographic information, identifiers, publisher's policy, and so on.
You can either access it directly from the attributes of the paper, for instance
with `self.paper.title`, or use the JSON representation that we generate for
`the API <https://dev.dissem.in/api.html>`_, which can be generated using `self.paper.json()`. For instance, `self.paper.json()['title']` gives you the title.

The PDF file is passed as an argument to the `submit_deposit` method. It
is a path to the PDF file, which you can open with `open(pdf, 'r')` for instance.

You also have access to the settings for the target repository, as a :class:`~deposit.models.Repository` object, in `self.repository`.
This should give you all the information you need about how to connect
to the repository: `self.repository.endpoint`, `self.repository.username`,
`self.repository.password`, and so on (see the documentation of :class:`~deposit.models.Repository` for more details).

If the deposit fails for any reason, you should raise :class:`protocol.DepositError`
with an helpful error message, like this::

   raise protocol.DepositError(_('The repository refused your paper.'))

Note that we localize the error (with the underscore function).

It is generally a good idea to log messages to keep track of how the deposit does.
You can use the embedded logger, so that your log messages will be saved by
Dissemin in the relevant DepositRecords, like this::

   self.log("Do not forget to log the responses you get from the server.")

Testing the protocol
--------------------

So now, how do you test this protocol implementation? Instead of testing
it manually by yourself, you are encouraged to take advantage of the testing
framework available in Dissemin. You will write test cases, that check
the behaviour of your implementation for particular PDF files and paper metadata.

To do so, we will create a file at `deposit/sword/tests.py` with the following
code::

   from deposit.tests import ProtocolTest, lorem_ipsum
   # lorem_ipsum contains a sample abstract you can reuse in your test case

   class SwordProtocolTest(ProtocolTest):
       @classmethod
       def setUpClass(self):
            super(SwordProtocolTest, self).setUpClass()

            # Fill here the details of your test repository
            self.repo.username = 'dspacedemo+submit@gmail.com'
            self.repo.password = 'dspace'
            self.repo.endpoint = 'http://demo.dspace.org/swordv2/servicedocument'

            # Now we set up the protocol for the tests
            self.proto = SwordProtocol(self.repo)

            # Fill here the details of the metadata form for your repository
            data = {'onbehalfof':'dspacedemo+colladmin@gmail.com'}
            self.form = self.proto.get_bound_form(data)
            self.form.is_valid() # this validates our sample data

So, once you have done that, you migth think that you have not written any test.
In fact, as your test case subclasses :class:`~deposit.tests.ProtocolTest`,
it inherits various test cases, including one that will try to submit a PDF
to the repository you have defined, with the contents of the form as above.

To try it out, run the following command at the root of your Dissemin instance::

   python manage.py test deposit.sword.tests


It is a very good idea to add more test cases, for instance by creating
multiple subclasses of :class:`~deposit.tests.ProtocolTest` as above, or by
adding other tests methods to the same subclass (they have to

Using the protocol
------------------

So now you have your shiny new protocol implementation and you
want to use it.

First, we need to register the protocol in Dissemin. To do so,
add the following lines at the end of `deposit/sword/protocol.py`::

    from deposit.registry import *
    protocol_registry.register(SwordProtocol)

Next, add your protocol to the enabled apps, by adding `deposit.sword` in
the `INSTALLED_APPS` list of `dissemin/settings/common.py`::

    ...
    'deposit',
    'deposit.zenodo',
    'deposit.sword',
    ...

Now the final step is to configure a repository using that protocol.
Launch Dissemin, go to Django's web admin, click `Repositories`
and add a new repository, filling in all the configuration details
of that repository. The `Protocol` field should be filled by the
name of your protocol, `SwordProtocol` in our case.

Now, when you go to a paper page and try to deposit it, your repository
should show up, and if everything went well you should be able to deposit
papers.

Each deposit (successful or not) creates a :class:`~deposit.models.DepositRecord`
object that you can see from the web admin interface. If you have used
the provided log function, the logs of your deposits are available there.

To debug the protocol directly from the site, you can enable Django's `settings.DEBUG`
(in `dissemin/settings.py`) so that exceptions raised by your code are
popped up to the user.

Adding extra metadata with forms
--------------------------------

What if the repository you submit to requires additional metadata, that
Dissemin does not always provide? We need to add a field in the deposit form
to let the user fill this gap.

Fortunately, Django has `a very convenient interface to deal with
forms <https://docs.djangoproject.com/en/1.9/topics/forms/#building-a-form-in-django>`_,
so it should be quite straightforward to add the fields you need.

Let's say that the repository we want to deposit into takes two additional
pieces of information: the topic of the paper (in a set of predefined categories)
and an optional comment for the moderators.

All we need to do is to define a form with these two fields::

    # import the forms API
    from django import forms
    # import localization
    from django.utils.translation import ugettext_lazy as _

    # First, we define the possible topics for a submission
    MYREPO_TOPIC_CHOICES = [
        ('quantum epistemology',_('Quantum Epistemology')),
        ('neural petrochemistry',_('Neural Petrochemistry')),
        ('ethnography of predicative turbulence',_('Ethnography of Predicative Turbulence')),
        ('other',_('Other')),
        ]

    # Then, we define our metadata form
    class MyRepoForm(forms.Form):

        # Fields are declared as class arguments
        topic = forms.ChoiceField(
            label=_('Topic'), # the label that will be displayed on the field
            choices=MYREPO_TOPIC_CHOICES, # the possible choices for the user
            required=True, # is this field mandatory?
            # other arguments are possible, see https://docs.djangoproject.com/en/1.9/ref/forms/fields/
            )

        comment = forms.CharField(
             label=_('Comment for the moderators'),
             required=False)



Then, we need to bind this form to our protocol. TODO

