from django import template
from publish.forms import PublishPreviewForm
register = template.Library()


def show_admin_bar(context, object):
    return {
        'request': context['request'],
        'object': object,
        'publish_preview_form': PublishPreviewForm()
    }
register.inclusion_tag('publish/admin/admin_bar.html',
                        takes_context=True)(show_admin_bar)
