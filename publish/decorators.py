try:
    from functools import wraps
except ImportError:
    from django.utils.functional import wraps  # Python 2.4 fallback.

from django.http import Http404


def staff_only_preview(view_func):
    def _checkstaff(request, *args, **kwargs):
        if request.user.is_active and request.user.is_staff:
            kwargs['preview'] = True
            return view_func(request, *args, **kwargs)
        raise Http404
    return wraps(view_func)(_checkstaff)
