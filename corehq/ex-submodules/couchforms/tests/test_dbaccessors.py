from django.test import TestCase
from couchforms.dbaccessors import get_forms_by_type, clear_all_forms, \
    get_number_of_forms_by_type, get_number_of_forms_of_all_types, \
    get_form_ids_by_type
from couchforms.models import XFormInstance, XFormError


class TestDBAccessors(TestCase):

    @classmethod
    def setUpClass(cls):
        cls.domain = 'evelyn'

        cls.xforms = [XFormInstance(_id='xform_1'), XFormInstance(_id='xform_2')]
        cls.xform_errors = [XFormError(_id='xform_error_1')]

        for form in cls.xforms + cls.xform_errors:
            form.domain = cls.domain
            form.save()

    @classmethod
    def tearDownClass(cls):
        clear_all_forms(cls.domain)

    def test_get_forms_by_type_xforminstance(self):
        forms = get_forms_by_type(self.domain, 'XFormInstance', limit=10)
        self.assertEqual(len(forms), len(self.xforms))
        self.assertEqual({form._id for form in forms},
                         {form._id for form in self.xforms})
        for form in forms:
            self.assertIsInstance(form, XFormInstance)

    def test_get_forms_by_type_xformerror(self):
        forms = get_forms_by_type(self.domain, 'XFormError', limit=10)
        self.assertEqual(len(forms), len(self.xform_errors))
        self.assertEqual({form._id for form in forms},
                         {form._id for form in self.xform_errors})
        for form in forms:
            self.assertIsInstance(form, XFormError)

    def test_get_number_of_forms_by_type_xforminstance(self):
        self.assertEqual(
            get_number_of_forms_by_type(self.domain, 'XFormInstance'),
            len(self.xforms)
        )

    def test_get_number_of_forms_by_type_xformerror(self):
        self.assertEqual(
            get_number_of_forms_by_type(self.domain, 'XFormError'),
            len(self.xform_errors)
        )

    def test_get_number_of_forms_of_all_types(self):
        self.assertEqual(
            get_number_of_forms_of_all_types(self.domain),
            len(self.xforms) + len(self.xform_errors)
        )

    def test_get_form_ids_by_type(self):
        form_ids = get_form_ids_by_type(self.domain, 'XFormError')
        self.assertEqual(form_ids, [form._id for form in self.xform_errors])
