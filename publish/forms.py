import datetime
from django import forms

from widgets import SplitSelectDateTimeWidget


class PublishPreviewForm(forms.Form):
    preview_at = forms.DateTimeField(required=False,
            widget=SplitSelectDateTimeWidget(second_step=30),
            initial=datetime.datetime.now(),
            label='or, preview the site as it will look on:')
