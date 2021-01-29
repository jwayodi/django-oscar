from django import forms
from django.db import transaction
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from oscar.apps.voucher.utils import get_unused_code
from oscar.core.loading import get_model
from oscar.forms import widgets

Voucher = get_model('voucher', 'Voucher')
VoucherSet = get_model('voucher', 'VoucherSet')
ConditionalOffer = get_model('offer', 'ConditionalOffer')


class VoucherForm(forms.Form):
    """
    A specialised form for creating a voucher and offer
    model.
    """
    name = forms.CharField(label=_("Name"))
    code = forms.CharField(label=_("Code"))

    start_datetime = forms.DateTimeField(
        widget=widgets.DateTimePickerInput(),
        label=_("Start datetime"))
    end_datetime = forms.DateTimeField(
        widget=widgets.DateTimePickerInput(),
        label=_("End datetime"))

    usage = forms.ChoiceField(choices=(("", "---------"),) + Voucher.USAGE_CHOICES, label=_("Usage"))

    offers = forms.ModelMultipleChoiceField(
        label=_("Which offers apply for this voucher?"),
        queryset=ConditionalOffer.objects.filter(offer_type=ConditionalOffer.VOUCHER),
    )

    def __init__(self, voucher=None, *args, **kwargs):
        self.voucher = voucher
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data['name']
        try:
            voucher = Voucher.objects.get(name=name)
        except Voucher.DoesNotExist:
            pass
        else:
            if (not self.voucher) or (voucher.id != self.voucher.id):
                raise forms.ValidationError(_("The name '%s' is already in"
                                              " use") % name)
        return name

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        if not code:
            raise forms.ValidationError(_("Please enter a voucher code"))
        try:
            voucher = Voucher.objects.get(code=code)
        except Voucher.DoesNotExist:
            pass
        else:
            if (not self.voucher) or (voucher.id != self.voucher.id):
                raise forms.ValidationError(_("The code '%s' is already in"
                                              " use") % code)
        return code

    def clean(self):
        cleaned_data = super().clean()
        start_datetime = cleaned_data.get('start_datetime')
        end_datetime = cleaned_data.get('end_datetime')
        if start_datetime and end_datetime and end_datetime < start_datetime:
            raise forms.ValidationError(_("The start date must be before the"
                                          " end date"))
        return cleaned_data


class VoucherSearchForm(forms.Form):
    name = forms.CharField(required=False, label=_("Name"))
    code = forms.CharField(required=False, label=_("Code"))
    is_active = forms.NullBooleanField(
        required=False, label=_("Is Active?"), widget=forms.NullBooleanSelect(attrs={'class': 'no-widget-init'}))
    in_set = forms.NullBooleanField(
        required=False, label=_("In Voucher set?"), widget=forms.NullBooleanSelect(attrs={'class': 'no-widget-init'}))

    def clean_code(self):
        return self.cleaned_data['code'].upper()


class VoucherSetForm(forms.ModelForm):
    usage = forms.ChoiceField(choices=(("", "---------"),) + Voucher.USAGE_CHOICES, label=_("Usage"))

    offers = forms.ModelMultipleChoiceField(
        label=_("Which offers apply for this voucher set?"),
        queryset=ConditionalOffer.objects.filter(offer_type=ConditionalOffer.VOUCHER),
    )

    class Meta:
        model = VoucherSet
        fields = [
            'name',
            'code_length',
            'description',
            'start_datetime',
            'end_datetime',
            'count',
        ]
        widgets = {
            'start_datetime': widgets.DateTimePickerInput(),
            'end_datetime': widgets.DateTimePickerInput(),
        }

    def clean_count(self):
        data = self.cleaned_data['count']
        if (self.instance.pk is not None) and (data < self.instance.count):
            stats_url = reverse('dashboard:voucher-set-detail', kwargs={'pk': self.instance.pk})
            raise forms.ValidationError(mark_safe(
                _('This cannot be used to delete vouchers (currently %s) in this set. '
                  'You can do that on the <a href="%s">detail</a> page.') % (self.instance.count, stats_url)))
        return data

    @transaction.atomic
    def save(self, commit=True):
        instance = super().save(commit)
        if commit:
            Voucher = get_model('voucher', 'Voucher')
            usage = self.cleaned_data['usage']
            offers = self.cleaned_data['offers']
            if instance is not None:
                # Update vouchers in this set
                instance.vouchers.update(name=instance.name,
                                         usage=usage,
                                         start_datetime=instance.start_datetime,
                                         end_datetime=instance.end_datetime)
                for voucher in instance.vouchers.all():
                    voucher.offers.set(offers)
            # Add vouchers to this set
            vouchers_added = False
            for i in range(instance.vouchers.count(), instance.count):
                voucher = Voucher.objects.create(name=instance.name,
                                                 code=get_unused_code(length=instance.code_length),
                                                 voucher_set=instance,
                                                 usage=usage,
                                                 start_datetime=instance.start_datetime,
                                                 end_datetime=instance.end_datetime)
                voucher.offers.add(*offers)
                vouchers_added = True
            if vouchers_added:
                instance.update_count()
        return instance


class VoucherSetSearchForm(forms.Form):
    code = forms.CharField(required=False, label=_("Code"))

    def clean_code(self):
        return self.cleaned_data['code'].upper()
