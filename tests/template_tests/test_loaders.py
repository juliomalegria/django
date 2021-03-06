"""
Test cases for the template loaders

Note: This test requires setuptools!
"""

import os.path
import sys
import types
import unittest

try:
    import pkg_resources
except ImportError:
    pkg_resources = None


from django.template import TemplateDoesNotExist, Context
from django.template.loaders import cached, eggs
from django.template.engine import Engine
from django.template import loader
from django.test import SimpleTestCase, ignore_warnings, override_settings
from django.utils import six
from django.utils.deprecation import RemovedInDjango20Warning
from django.utils._os import upath
from django.utils.six import StringIO


TEMPLATES_DIR = os.path.join(os.path.dirname(upath(__file__)), 'templates')

GLOBAL_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(upath(__file__))), 'templates')


# Mock classes and objects for pkg_resources functions.
class MockLoader(object):
    pass


def create_egg(name, resources):
    """
    Creates a mock egg with a list of resources.

    name: The name of the module.
    resources: A dictionary of resources. Keys are the names and values the data.
    """
    egg = types.ModuleType(name)
    egg.__loader__ = MockLoader()
    egg.__path__ = ['/some/bogus/path/']
    egg.__file__ = '/some/bogus/path/__init__.pyc'
    egg._resources = resources
    sys.modules[name] = egg


@unittest.skipUnless(pkg_resources, 'setuptools is not installed')
class EggLoaderTest(SimpleTestCase):

    def setUp(self):
        self.loader = eggs.Loader(Engine.get_default())

        # Defined here b/c at module scope we may not have pkg_resources
        class MockProvider(pkg_resources.NullProvider):
            def __init__(self, module):
                pkg_resources.NullProvider.__init__(self, module)
                self.module = module

            def _has(self, path):
                return path in self.module._resources

            def _isdir(self, path):
                return False

            def get_resource_stream(self, manager, resource_name):
                return self.module._resources[resource_name]

            def _get(self, path):
                return self.module._resources[path].read()

            def _fn(self, base, resource_name):
                return os.path.normcase(resource_name)

        pkg_resources._provider_factories[MockLoader] = MockProvider

        self.empty_egg = create_egg("egg_empty", {})
        self.egg_1 = create_egg("egg_1", {
            os.path.normcase('templates/y.html'): StringIO("y"),
            os.path.normcase('templates/x.txt'): StringIO("x"),
        })

    @override_settings(INSTALLED_APPS=['egg_empty'])
    def test_empty(self):
        "Loading any template on an empty egg should fail"
        with self.assertRaises(TemplateDoesNotExist):
            self.loader.load_template_source("not-existing.html")

    @override_settings(INSTALLED_APPS=['egg_1'])
    def test_non_existing(self):
        "Template loading fails if the template is not in the egg"
        with self.assertRaises(TemplateDoesNotExist):
            self.loader.load_template_source("not-existing.html")

    @override_settings(INSTALLED_APPS=['egg_1'])
    def test_existing(self):
        "A template can be loaded from an egg"
        contents, template_name = self.loader.load_template_source("y.html")
        self.assertEqual(contents, "y")
        self.assertEqual(template_name, "egg:egg_1:templates/y.html")

    def test_not_installed(self):
        "Loading an existent template from an egg not included in any app should fail"
        with self.assertRaises(TemplateDoesNotExist):
            self.loader.load_template_source("y.html")


class CachedLoader(SimpleTestCase):

    def setUp(self):
        self.loader = cached.Loader(Engine.get_default(), [
            'django.template.loaders.filesystem.Loader',
        ])

    def test_templatedir_caching(self):
        "Check that the template directories form part of the template cache key. Refs #13573"
        # Retrieve a template specifying a template directory to check
        t1, name = self.loader.find_template('test.html', (os.path.join(TEMPLATES_DIR, 'first'),))
        # Now retrieve the same template name, but from a different directory
        t2, name = self.loader.find_template('test.html', (os.path.join(TEMPLATES_DIR, 'second'),))

        # The two templates should not have the same content
        self.assertNotEqual(t1.render(Context({})), t2.render(Context({})))

    def test_missing_template_is_cached(self):
        "#19949 -- Check that the missing template is cached."
        # Check that 'missing.html' isn't already in cache before 'missing.html' is loaded
        with self.assertRaises(KeyError):
            self.loader.template_cache["missing.html"]
        # Try to load it, it should fail
        with self.assertRaises(TemplateDoesNotExist):
            self.loader.load_template("missing.html")
        # Verify that the fact that the missing template, which hasn't been found, has actually
        # been cached:
        cached_miss = self.loader.template_cache["missing.html"]
        self.assertEqual(cached_miss, TemplateDoesNotExist,
                         "Cached template loader doesn't cache file lookup misses. It should.")


@override_settings(TEMPLATES=[{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [TEMPLATES_DIR],
}])
class RenderToStringTest(SimpleTestCase):
    def test_basic(self):
        self.assertEqual(loader.render_to_string('test_context.html'), 'obj:\n')

    def test_basic_context(self):
        self.assertEqual(loader.render_to_string('test_context.html',
                                                 {'obj': 'test'}), 'obj:test\n')

    def test_empty_list(self):
        six.assertRaisesRegex(self, TemplateDoesNotExist,
            'No template names provided$',
            loader.render_to_string, [])

    def test_select_templates_from_empty_list(self):
        six.assertRaisesRegex(self, TemplateDoesNotExist,
            'No template names provided$',
            loader.select_template, [])


@ignore_warnings(category=RemovedInDjango20Warning)
@override_settings(TEMPLATES=[{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [TEMPLATES_DIR],
}])
class DeprecatedRenderToStringTest(SimpleTestCase):

    def test_existing_context_kept_clean(self):
        context = Context({'obj': 'before'})
        output = loader.render_to_string('test_context.html', {'obj': 'after'},
                                         context_instance=context)
        self.assertEqual(output, 'obj:after\n')
        self.assertEqual(context['obj'], 'before')

    def test_no_empty_dict_pushed_to_stack(self):
        """
        No empty dict should be pushed to the context stack when render_to_string
        is called without any argument (#21741).
        """

        # The stack should have a length of 1, corresponding to the builtins
        self.assertEqual('1',
            loader.render_to_string('test_context_stack.html').strip())
        self.assertEqual('1',
            loader.render_to_string('test_context_stack.html', context_instance=Context()).strip())


@ignore_warnings(category=RemovedInDjango20Warning)
@override_settings(TEMPLATES=[{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
}])
class TemplateDirsOverrideTest(SimpleTestCase):

    dirs_tuple = (os.path.join(os.path.dirname(upath(__file__)), 'other_templates'),)
    dirs_list = list(dirs_tuple)
    dirs_iter = (dirs_tuple, dirs_list)

    def test_render_to_string(self):
        for dirs in self.dirs_iter:
            self.assertEqual(loader.render_to_string('test_dirs.html', dirs=dirs), 'spam eggs\n')

    def test_get_template(self):
        for dirs in self.dirs_iter:
            template = loader.get_template('test_dirs.html', dirs=dirs)
            self.assertEqual(template.render(), 'spam eggs\n')

    def test_select_template(self):
        for dirs in self.dirs_iter:
            template = loader.select_template(['test_dirs.html'], dirs=dirs)
            self.assertEqual(template.render(), 'spam eggs\n')


@override_settings(TEMPLATES=[{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [GLOBAL_TEMPLATES_DIR],
    'OPTIONS': {
        'loaders': [
            ('django.template.loaders.cached.Loader', [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
            ]),
        ],
    },
}])
class PriorityCacheLoader(SimpleTestCase):
    def test_basic(self):
        """
        Check that the order of template loader works. Refs #21460.
        """
        t1 = loader.get_template('priority/foo.html')
        self.assertEqual(t1.render(), 'priority\n')


@override_settings(TEMPLATES=[{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [GLOBAL_TEMPLATES_DIR],
    'OPTIONS': {
        'loaders': [
            'django.template.loaders.filesystem.Loader',
            'django.template.loaders.app_directories.Loader',
        ],
    },
}])
class PriorityLoader(SimpleTestCase):
    def test_basic(self):
        """
        Check that the order of template loader works. Refs #21460.
        """
        t1 = loader.get_template('priority/foo.html')
        self.assertEqual(t1.render(), 'priority\n')
