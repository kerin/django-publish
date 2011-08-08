from datetime import datetime

from django.contrib import admin
from django.shortcuts import get_object_or_404, render_to_response
from django.core.exceptions import PermissionDenied
from django.contrib.admin.util import unquote
from django import template
from django.utils.encoding import force_unicode, smart_unicode
from django.utils.safestring import mark_safe
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin.filterspecs import FilterSpec, RelatedFilterSpec
from django.forms.models import BaseInlineFormSet

from models import Publishable
from actions import publish_selected, delete_selected, undelete_selected

class PublishableRelatedFilterSpec(RelatedFilterSpec):
    def __init__(self, f, request, params, model, model_admin):
        super(PublishableRelatedFilterSpec, self).__init__(f, request, params, model, model_admin)
        # to keep things simple we'll just remove all "non-draft" instance from list
        rel_model = f.rel.to
        queryset = rel_model._default_manager.complex_filter(f.rel.limit_choices_to).draft_and_deleted()
        if hasattr(f.rel, 'get_related_field'):
            lst = [(getattr(x, f.rel.get_related_field().attname), smart_unicode(x)) for x in queryset]
        else:
            lst = [(x._get_pk_val(), smart_unicode(x)) for x in queryset]
        self.lookup_choices = lst

def is_publishable_spec(f):
    return bool(f.rel) and issubclass(f.rel.to, Publishable)

def register_filter_spec(test, factory):
    # NB this may need updating for Django 1.2,
    # but basically we want this to get run before
    # RelatedFilterSpec - 1.2 should have a method to do this
    FilterSpec.filter_specs.insert(0, (test, factory))

register_filter_spec(is_publishable_spec, PublishableRelatedFilterSpec)

def _make_form_readonly(form):
    for field in form.fields.values():
        # some widget wrap other widgets in admin
        widget = field.widget
        if hasattr(widget, 'widget'):
            widget = getattr(widget, 'widget')
        widget.attrs['disabled'] = 'disabled'


def _make_adminform_readonly(adminform, inline_admin_formsets):
    _make_form_readonly(adminform.form)
    for admin_formset in inline_admin_formsets:
        for form in admin_formset.formset.forms:
            _make_form_readonly(form)

def _draft_queryset(db_field, kwargs):
    # see if we need to filter the field's queryset
    model = db_field.rel.to
    if issubclass(model, Publishable):
        kwargs['queryset'] = model._default_manager.draft()

def attach_filtered_formfields(admin_class):
    # class decorator to add in extra methods that
    # are common to several classes
    super_formfield_for_foreignkey = admin_class.formfield_for_foreignkey
    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        _draft_queryset(db_field, kwargs)
        return super_formfield_for_foreignkey(self, db_field, request, **kwargs)
    admin_class.formfield_for_foreignkey = formfield_for_foreignkey

    super_formfield_for_manytomany = admin_class.formfield_for_manytomany
    def formfield_for_manytomany(self, db_field, request=None, **kwargs):
        _draft_queryset(db_field, kwargs)
        return super_formfield_for_manytomany(self, db_field, request, **kwargs)
    admin_class.formfield_for_manytomany = formfield_for_manytomany
    return admin_class

class PublishableAdmin(admin.ModelAdmin):

    actions = [publish_selected, delete_selected, undelete_selected]
    change_form_template = 'admin/publish_change_form.html'
    publish_confirmation_template = None
    deleted_form_template = None

    list_display = ['__unicode__', 'publish_status']
    list_filter = ['publish_state']

    def queryset(self, request):
        # we want to show draft and deleted
        # objects in changelist in admin
        # so we can let the user select and publish them
        qs = super(PublishableAdmin, self).queryset(request)
        return qs.draft_and_deleted()

    def get_actions(self, request):
        actions = super(PublishableAdmin, self).get_actions(request)
        # replace site-wide delete selected with our own version
        if 'delete_selected' in actions:
            actions['delete_selected'] = (delete_selected, 'delete_selected', delete_selected.short_description)
        return actions

    def has_change_permission(self, request, obj=None):
        # user can never change public models directly
        # but can view old read-only copy of it if we are about to delete it
        if obj:
            if obj.is_public or (request.method == 'POST' and obj.publish_state == Publishable.PUBLISH_DELETE):
                return False
        return super(PublishableAdmin, self).has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # use can never delete models directly
        if obj and obj.is_public:
            return False
        return super(PublishableAdmin, self).has_delete_permission(request, obj)

    def has_publish_permission(self, request, obj=None):
        opts = self.opts
        return request.user.has_perm(opts.app_label + '.' + opts.get_publish_permission())

    def publish_status(self, obj):
        return self.get_publish_status_display(obj)

    def get_publish_status_display(self, obj):
        state = obj.get_publish_state_display()
        if not obj.is_public and not obj.public:
            state = '%s - not yet published' % state
        if obj.public and obj.public.publish_at and obj.public.publish_at > datetime.now():
            state = 'Scheduled to go live at %s' % obj.public.publish_at
            if obj.publish_state == Publishable.PUBLISH_CHANGED:
                state = '%s - has changes awaiting approval' % state
        return state

    def log_publication(self, request, object):
        # only log objects that we should
        if isinstance(object, Publishable):
            model = object.__class__
            other_modeladmin = self.admin_site._registry.get(model, None)
            if other_modeladmin:
                # just log as a change
                self.log_change(request, object, 'Published')

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context['has_publish_permission'] = self.has_publish_permission(request, obj)

        if obj and obj.publish_state == Publishable.PUBLISH_DELETE:
            adminform, inline_admin_formsets = context['adminform'], context['inline_admin_formsets']
            _make_adminform_readonly(adminform, inline_admin_formsets)

            context.update({
                'title': 'This %s will be deleted' % force_unicode(self.opts.verbose_name),
            })

        return super(PublishableAdmin, self).render_change_form(request, context, add, change, form_url, obj)

class PublishableBaseInlineFormSet(BaseInlineFormSet):
    # we will actually delete inline objects, rather than
    # just marking them for deletion, as they are like
    # an edit to their parent

    def save_existing_objects(self, commit=True):
        saved_instances = super(PublishableBaseInlineFormSet, self).save_existing_objects(commit=commit)
        for obj in self.deleted_objects:
            if obj.pk is not None:
                obj.delete(mark_for_deletion=False)
        return saved_instances

class PublishableStackedInline(admin.StackedInline):
    formset = PublishableBaseInlineFormSet

class PublishableTabularInline(admin.TabularInline):
    formset = PublishableBaseInlineFormSet

# add in extra methods
for admin_class in [PublishableAdmin, PublishableStackedInline, PublishableTabularInline]:
    attach_filtered_formfields(admin_class)
