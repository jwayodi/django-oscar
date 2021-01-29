import csv

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import generic

from oscar.core.loading import get_class, get_model
from oscar.core.utils import slugify
from oscar.views import sort_queryset

VoucherForm = get_class('dashboard.vouchers.forms', 'VoucherForm')
VoucherSetForm = get_class('dashboard.vouchers.forms', 'VoucherSetForm')
VoucherSetSearchForm = get_class('dashboard.vouchers.forms', 'VoucherSetSearchForm')
VoucherSearchForm = get_class('dashboard.vouchers.forms', 'VoucherSearchForm')
Voucher = get_model('voucher', 'Voucher')
VoucherSet = get_model('voucher', 'VoucherSet')
OrderDiscount = get_model('order', 'OrderDiscount')


class VoucherListView(generic.ListView):
    model = Voucher
    context_object_name = 'vouchers'
    template_name = 'oscar/dashboard/vouchers/voucher_list.html'
    form_class = VoucherSearchForm
    description_template = _("%(main_filter)s %(name_filter)s %(code_filter)s")
    paginate_by = settings.OSCAR_DASHBOARD_ITEMS_PER_PAGE

    def get_queryset(self):
        qs = self.model.objects.all().order_by('-date_created')
        qs = sort_queryset(qs, self.request,
                           ['num_basket_additions', 'num_orders',
                            'date_created'],
                           '-date_created')
        self.description_ctx = {'main_filter': _('All vouchers'),
                                'name_filter': '',
                                'code_filter': ''}

        # If form not submitted, return early
        if not self.request.GET:
            self.form = self.form_class(initial={'in_set': False})
            return qs.filter(voucher_set__isnull=True)

        self.form = self.form_class(self.request.GET)
        if not self.form.is_valid():
            return qs

        data = self.form.cleaned_data
        if data['name']:
            qs = qs.filter(name__icontains=data['name'])
            self.description_ctx['name_filter'] \
                = _("with name matching '%s'") % data['name']
        if data['code']:
            qs = qs.filter(code=data['code'])
            self.description_ctx['code_filter'] \
                = _("with code '%s'") % data['code']
        if data['is_active'] is not None:
            now = timezone.now()
            if data['is_active']:
                qs = qs.filter(start_datetime__lte=now, end_datetime__gte=now)
                main_filter = _('Active vouchers')
            else:
                qs = qs.filter(end_datetime__lt=now)
                main_filter = _('Inactive vouchers')
            self.description_ctx['main_filter'] = main_filter

        if data['in_set'] is not None:
            qs = qs.filter(voucher_set__isnull=not data['in_set'])

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.form.is_bound:
            description = self.description_template % self.description_ctx
        else:
            description = _("Vouchers")
        ctx['description'] = description
        ctx['form'] = self.form
        return ctx


class VoucherCreateView(generic.FormView):
    model = Voucher
    template_name = 'oscar/dashboard/vouchers/voucher_form.html'
    form_class = VoucherForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Create voucher')
        return ctx

    def get_initial(self):
        return {
            'start_datetime': timezone.now(),
        }

    @transaction.atomic()
    def form_valid(self, form):
        voucher = Voucher.objects.create(
            name=form.cleaned_data['name'],
            code=form.cleaned_data['code'],
            usage=form.cleaned_data['usage'],
            start_datetime=form.cleaned_data['start_datetime'],
            end_datetime=form.cleaned_data['end_datetime'],
        )
        voucher.offers.add(*form.cleaned_data['offers'])
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        messages.success(self.request, _("Voucher created"))
        return reverse('dashboard:voucher-list')


class VoucherStatsView(generic.DetailView):
    model = Voucher
    template_name = 'oscar/dashboard/vouchers/voucher_detail.html'
    context_object_name = 'voucher'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        discounts = OrderDiscount.objects.filter(voucher_id=self.object.id)
        discounts = discounts.order_by('-order__date_placed')
        ctx['discounts'] = discounts
        return ctx


class VoucherUpdateView(generic.FormView):
    template_name = 'oscar/dashboard/vouchers/voucher_form.html'
    model = Voucher
    form_class = VoucherForm

    def dispatch(self, request, *args, **kwargs):
        voucher_set = self.get_voucher().voucher_set
        if voucher_set is not None:
            messages.warning(request, _("The voucher can only be edited as part of its set"))
            return redirect('dashboard:voucher-set-update', pk=voucher_set.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_voucher(self):
        if not hasattr(self, 'voucher'):
            self.voucher = Voucher.objects.get(id=self.kwargs['pk'])
        return self.voucher

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = self.voucher.name
        ctx['voucher'] = self.voucher
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['voucher'] = self.get_voucher()
        return kwargs

    def get_initial(self):
        voucher = self.get_voucher()
        return {
            'name': voucher.name,
            'code': voucher.code,
            'start_datetime': voucher.start_datetime,
            'end_datetime': voucher.end_datetime,
            'usage': voucher.usage,
            'offers': voucher.offers.all(),
        }

    @transaction.atomic()
    def form_valid(self, form):
        voucher = self.get_voucher()
        voucher.name = form.cleaned_data['name']
        voucher.code = form.cleaned_data['code']
        voucher.usage = form.cleaned_data['usage']
        voucher.start_datetime = form.cleaned_data['start_datetime']
        voucher.end_datetime = form.cleaned_data['end_datetime']
        voucher.save()

        voucher.offers.set(form.cleaned_data['offers'])

        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        messages.success(self.request, _("Voucher updated"))
        return reverse('dashboard:voucher-list')


class VoucherDeleteView(generic.DeleteView):
    model = Voucher
    template_name = 'oscar/dashboard/vouchers/voucher_delete.html'
    context_object_name = 'voucher'

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        response = super().delete(request, *args, **kwargs)
        if self.object.voucher_set is not None:
            self.object.voucher_set.update_count()
        return response

    def get_success_url(self):
        messages.warning(self.request, _("Voucher deleted"))
        if self.object.voucher_set is not None:
            return reverse('dashboard:voucher-set-detail', kwargs={'pk': self.object.voucher_set.pk})
        else:
            return reverse('dashboard:voucher-list')


class VoucherSetCreateView(generic.CreateView):
    model = VoucherSet
    template_name = 'oscar/dashboard/vouchers/voucher_set_form.html'
    form_class = VoucherSetForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Create voucher set')
        return ctx

    def get_initial(self):
        return {
            'start_datetime': timezone.now(),
        }

    def get_success_url(self):
        messages.success(self.request, _("Voucher set created"))
        return reverse('dashboard:voucher-set-list')


class VoucherSetUpdateView(generic.UpdateView):
    template_name = 'oscar/dashboard/vouchers/voucher_set_form.html'
    model = VoucherSet
    context_object_name = 'voucher_set'
    form_class = VoucherSetForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = self.object.name
        return ctx

    def get_initial(self):
        initial = super().get_initial()
        # All vouchers in the set have the same "usage" and "offers", so we use
        # the first one
        voucher = self.object.vouchers.first()
        if voucher is not None:
            initial['usage'] = voucher.usage
            initial['offers'] = voucher.offers.all()
        return initial

    def get_success_url(self):
        messages.success(self.request, _("Voucher updated"))
        return reverse('dashboard:voucher-set-detail', kwargs={'pk': self.object.pk})


class VoucherSetDetailView(generic.ListView):

    model = Voucher
    context_object_name = 'vouchers'
    template_name = 'oscar/dashboard/vouchers/voucher_set_detail.html'
    form_class = VoucherSetSearchForm
    description_template = _("%(main_filter)s %(name_filter)s %(code_filter)s")
    paginate_by = 50

    def dispatch(self, request, *args, **kwargs):
        self.voucher_set = get_object_or_404(VoucherSet, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = (
            self.model.objects
            .filter(voucher_set=self.voucher_set)
            .order_by('-date_created'))

        qs = sort_queryset(qs, self.request,
                           ['num_basket_additions', 'num_orders',
                            'date_created'],
                           '-date_created')
        self.description_ctx = {'main_filter': _('All vouchers'),
                                'name_filter': '',
                                'code_filter': ''}

        # If form not submitted, return early
        is_form_submitted = (
            'name' in self.request.GET or 'code' in self.request.GET
        )
        if not is_form_submitted:
            self.form = self.form_class()
            return qs

        self.form = self.form_class(self.request.GET)
        if not self.form.is_valid():
            return qs

        data = self.form.cleaned_data
        if data['code']:
            qs = qs.filter(code__icontains=data['code'])
            self.description_ctx['code_filter'] \
                = _("with code '%s'") % data['code']

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['voucher_set'] = self.voucher_set
        ctx['description'] = self.voucher_set.name
        ctx['form'] = self.form
        return ctx


class VoucherSetListView(generic.ListView):
    model = VoucherSet
    context_object_name = 'voucher_sets'
    template_name = 'oscar/dashboard/vouchers/voucher_set_list.html'
    description_template = _("%(main_filter)s %(name_filter)s %(code_filter)s")
    paginate_by = settings.OSCAR_DASHBOARD_ITEMS_PER_PAGE

    def get_queryset(self):
        qs = self.model.objects.all().order_by('-date_created')
        qs = sort_queryset(
            qs, self.request,
            ['num_basket_additions', 'num_orders', 'date_created'], '-date_created')
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        description = _("Voucher sets")
        ctx['description'] = description
        return ctx


class VoucherSetDownloadView(generic.DetailView):
    template_name = 'oscar/dashboard/vouchers/voucher_set_form.html'
    model = VoucherSet
    form_class = VoucherSetForm

    def get(self, request, *args, **kwargs):
        voucher_set = self.get_object()

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            'attachment; filename="%s.csv"' % slugify(voucher_set.name))

        writer = csv.writer(response)
        for code in voucher_set.vouchers.values_list('code', flat=True):
            writer.writerow([code])

        return response


class VoucherSetDeleteView(generic.DeleteView):
    model = VoucherSet
    template_name = 'oscar/dashboard/vouchers/voucher_set_delete.html'
    context_object_name = 'voucher_set'

    def get_success_url(self):
        messages.warning(self.request, _("Voucher set deleted"))
        return reverse('dashboard:voucher-set-list')
