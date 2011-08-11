from datetime import datetime


class PublishPreviewMiddleware(object):
    def process_request(self, request):

        if 'reset_preview_at' in request.GET:
            try:
                del request.session['preview_at']
            except KeyError:
                pass
            return None

        date_fields = ['preview_at_0_year', 'preview_at_0_month',
                        'preview_at_0_day', 'preview_at_1_hour',
                        'preview_at_1_minute']

        if request.user.is_staff and all(k in request.GET for k in date_fields):
            try:
                date_parts = [int(request.GET.get(i)) for i in date_fields]
                d = datetime(*date_parts)
                request.session['preview_at'] = d
            except:
                pass
