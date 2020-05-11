import json
import textwrap

import django_filters as filters
import django_tables2 as tables
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _
from django_tables2.utils import A
from wagtail.core.models import Page

from hypha.apply.categories.models import MetaTerm
from hypha.apply.funds.models import ApplicationSubmission, Round, ScreeningStatus
from hypha.apply.funds.workflow import STATUSES, get_review_active_statuses
from hypha.apply.review.models import Review
from hypha.apply.users.groups import STAFF_GROUP_NAME
from hypha.apply.utils.image import generate_image_tag
from hypha.images.models import CustomImage

from .widgets import Select2MultiCheckboxesWidget

User = get_user_model()


def review_filter_for_user(user):
    review_states = set(get_review_active_statuses(user))
    statuses = [
        name
        for name, status in STATUSES.items()
        if review_states & status
    ]
    return [
        slugify(status)
        for status in statuses
    ]


def make_row_class(record):
    css_class = 'submission-meta__row' if record.next else 'all-submissions-table__parent'
    css_class += '' if record.active else ' is-inactive'
    return css_class


def render_actions(table, record):
    user = table.context['user']
    actions = record.get_actions_for_user(user)
    return json.dumps([slugify(action) for _, action in actions])


def render_title(record):
    return textwrap.shorten(record.title, width=30, placeholder="...")


class SubmissionsTable(tables.Table):
    """Base table for listing submissions, do not include admin data to this table"""
    title = tables.LinkColumn('funds:submissions:detail', text=render_title, args=[A('pk')], orderable=True, attrs={'td': {'data-title-tooltip': lambda record: record.title, 'class': 'js-title'}})
    submit_time = tables.DateColumn(verbose_name="Submitted")
    phase = tables.Column(verbose_name="Status", order_by=('status',), attrs={'td': {'data-actions': render_actions, 'class': 'js-actions'}})
    stage = tables.Column(verbose_name="Type", order_by=('status',))
    fund = tables.Column(verbose_name="Fund", accessor='page')
    comments = tables.Column(accessor='comment_count', verbose_name="Comments")
    last_update = tables.DateColumn(accessor="last_update", verbose_name="Last updated")

    class Meta:
        model = ApplicationSubmission
        order_by = ('-last_update',)
        fields = ('title', 'phase', 'stage', 'fund', 'round', 'submit_time', 'last_update')
        sequence = fields + ('comments',)
        template_name = 'funds/tables/table.html'
        row_attrs = {
            'class': make_row_class,
            'data-record-id': lambda record: record.id,
        }
        attrs = {'class': 'all-submissions-table'}
        empty_text = _('No submissions available')

    def render_user(self, value):
        return value.get_full_name()

    def render_phase(self, value):
        return format_html('<span>{}</span>', value)

    def order_last_update(self, qs, desc):
        update_order = getattr(F('last_update'), 'desc' if desc else 'asc')(nulls_last=True)

        qs = qs.order_by(update_order, 'submit_time')
        return qs, True

    def get_column_class_names(self, classes_set, bound_column):
        classes_set = super(SubmissionsTable, self).get_column_class_names(classes_set, bound_column)
        classes_set.add(bound_column.name)
        return classes_set


class ReviewerSubmissionsTable(SubmissionsTable):
    class Meta(SubmissionsTable.Meta):
        orderable = False


class LabeledCheckboxColumn(tables.CheckBoxColumn):
    def wrap_with_label(self, checkbox, for_value):
        return format_html(
            '<label for="{}">{}</label>',
            for_value,
            checkbox,
        )

    @property
    def header(self):
        checkbox = super().header
        return self.wrap_with_label(checkbox, 'selectall')

    def render(self, value, record, bound_column):
        checkbox = super().render(value=value, record=record, bound_column=bound_column)
        return self.wrap_with_label(checkbox, value)


class BaseAdminSubmissionsTable(SubmissionsTable):
    lead = tables.Column(order_by=('lead.full_name',))
    reviews_stats = tables.TemplateColumn(template_name='funds/tables/column_reviews.html', verbose_name=mark_safe("Reviews<div>Assgn.\tComp.</div>"), orderable=False)
    screening_status = tables.Column(verbose_name="Screening")

    class Meta(SubmissionsTable.Meta):
        fields = ('title', 'phase', 'stage', 'fund', 'round', 'lead', 'submit_time', 'last_update', 'screening_status', 'reviews_stats')  # type: ignore
        sequence = fields + ('comments',)

    def render_lead(self, value):
        return format_html('<span>{}</span>', value)


class AdminSubmissionsTable(BaseAdminSubmissionsTable):
    """Adds admin only columns to the submissions table"""
    selected = LabeledCheckboxColumn(accessor=A('pk'), attrs={'input': {'class': 'js-batch-select'}, 'th__input': {'class': 'js-batch-select-all'}})

    class Meta(BaseAdminSubmissionsTable.Meta):
        fields = ('selected', *BaseAdminSubmissionsTable.Meta.fields)
        sequence = fields


class SummarySubmissionsTable(BaseAdminSubmissionsTable):
    class Meta(BaseAdminSubmissionsTable.Meta):
        orderable = False


class SummarySubmissionsTableWithRole(BaseAdminSubmissionsTable):
    """ Adds Role Assigned to the 'Waiting for My Review' table """
    role_icon = tables.Column(verbose_name="Role")

    class Meta(BaseAdminSubmissionsTable.Meta):
        sequence = ('...', 'role_icon', 'comments')
        orderable = False

    def render_role_icon(self, value):
        if value:
            image = CustomImage.objects.filter(id=value).first()
            if image:
                filter_spec = 'fill-20x20'
                return generate_image_tag(image, filter_spec)

        return ''


def get_used_rounds(request):
    return Round.objects.filter(submissions__isnull=False).distinct()


def get_used_funds(request):
    # Use page to pick up on both Labs and Funds
    return Page.objects.filter(applicationsubmission__isnull=False).distinct()


def get_round_leads(request):
    return User.objects.filter(submission_lead__isnull=False).distinct()


def get_reviewers(request):
    """ All assigned reviewers, staff or admin """
    return User.objects.filter(Q(submissions_reviewer__isnull=False) | Q(groups__name=STAFF_GROUP_NAME) | Q(is_superuser=True)).distinct()


def get_screening_statuses(request):
    return ScreeningStatus.objects.filter(
        id__in=ApplicationSubmission.objects.all().values('screening_status__id').distinct('screening_status__id'))


def get_meta_terms(request):
    return MetaTerm.objects.filter(
        id__in=ApplicationSubmission.objects.all().values('meta_terms__id').distinct('meta_terms__id'))


class Select2CheckboxWidgetMixin(filters.Filter):
    def __init__(self, *args, **kwargs):
        label = kwargs.get('label')
        kwargs.setdefault('widget', Select2MultiCheckboxesWidget(attrs={'data-placeholder': label}))
        super().__init__(*args, **kwargs)


class Select2MultipleChoiceFilter(Select2CheckboxWidgetMixin, filters.MultipleChoiceFilter):
    pass


class Select2ModelMultipleChoiceFilter(Select2MultipleChoiceFilter, filters.ModelMultipleChoiceFilter):
    pass


class StatusMultipleChoiceFilter(Select2MultipleChoiceFilter):
    def __init__(self, limit_to, *args, **kwargs):
        choices = [
            (slugify(name), name)
            for name, statuses in STATUSES.items()
            if not limit_to or self.has_any(statuses, limit_to)
        ]
        self.status_map = {
            slugify(name): status
            for name, status in STATUSES.items()
        }
        super().__init__(
            *args,
            field_name='status',
            choices=choices,
            label='Statuses',
            **kwargs,
        )

    def has_any(self, first, second):
        return any(item in second for item in first)

    def get_filter_predicate(self, v):
        return {f'{ self.field_name }__in': self.status_map[v]}


class SubmissionFilter(filters.FilterSet):
    round = Select2ModelMultipleChoiceFilter(queryset=get_used_rounds, label='Rounds')
    fund = Select2ModelMultipleChoiceFilter(field_name='page', queryset=get_used_funds, label='Funds')
    lead = Select2ModelMultipleChoiceFilter(queryset=get_round_leads, label='Leads')
    reviewers = Select2ModelMultipleChoiceFilter(queryset=get_reviewers, label='Reviewers')
    screening_status = Select2ModelMultipleChoiceFilter(queryset=get_screening_statuses, label='Screening')
    meta_terms = Select2ModelMultipleChoiceFilter(queryset=get_meta_terms, label='Terms')

    class Meta:
        model = ApplicationSubmission
        fields = ('fund', 'round', 'status')

    def __init__(self, *args, exclude=list(), limit_statuses=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.filters['status'] = StatusMultipleChoiceFilter(limit_to=limit_statuses)

        self.filters = {
            field: filter
            for field, filter in self.filters.items()
            if field not in exclude
        }


class SubmissionFilterAndSearch(SubmissionFilter):
    query = filters.CharFilter(field_name='search_data', lookup_expr="icontains", widget=forms.HiddenInput)


class SubmissionDashboardFilter(filters.FilterSet):
    round = Select2ModelMultipleChoiceFilter(queryset=get_used_rounds, label='Rounds')
    fund = Select2ModelMultipleChoiceFilter(field_name='page', queryset=get_used_funds, label='Funds')

    class Meta:
        model = ApplicationSubmission
        fields = ('fund', 'round')

    def __init__(self, *args, exclude=list(), limit_statuses=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.filters = {
            field: filter
            for field, filter in self.filters.items()
            if field not in exclude
        }


class SubmissionReviewerFilterAndSearch(SubmissionDashboardFilter):
    query = filters.CharFilter(field_name='search_data', lookup_expr="icontains", widget=forms.HiddenInput)


class RoundsTable(tables.Table):
    title = tables.LinkColumn('funds:rounds:detail', args=[A('pk')], orderable=True, text=lambda record: record.title)
    fund = tables.Column(accessor=A('specific.fund'))
    lead = tables.Column()
    start_date = tables.Column()
    end_date = tables.Column()
    progress = tables.Column(verbose_name="Determined")

    class Meta:
        fields = ('title', 'fund', 'lead', 'start_date', 'end_date', 'progress')
        attrs = {'class': 'responsive-table'}

    def render_lead(self, value):
        return format_html('<span>{}</span>', value)

    def render_progress(self, record):
        return f'{record.progress}%'

    def _field_order(self, field, desc):
        return getattr(F(f'{field}'), 'desc' if desc else 'asc')(nulls_last=True)

    def order_start_date(self, qs, desc):
        return qs.order_by(self._field_order('start_date', desc)), True

    def order_end_date(self, qs, desc):
        return qs.order_by(self._field_order('end_date', desc)), True

    def order_fund(self, qs, desc):
        return qs.order_by(self._field_order('fund', desc)), True

    def order_progress(self, qs, desc):
        return qs.order_by(self._field_order('progress', desc)), True

    def get_column_class_names(self, classes_set, bound_column):
        classes_set = super(RoundsTable, self).get_column_class_names(classes_set, bound_column)
        classes_set.add(bound_column.name)
        return classes_set


class ActiveRoundFilter(Select2MultipleChoiceFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(self, *args, choices=[('active', 'Active'), ('inactive', 'Inactive')], **kwargs)

    def filter(self, qs, value):
        if value is None or len(value) != 1:
            return qs

        value = value[0]
        if value == 'active':
            return qs.active()
        else:
            return qs.inactive()


class OpenRoundFilter(Select2MultipleChoiceFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(self, *args, choices=[('open', 'Open'), ('closed', 'Closed'), ('new', 'Not Started')], **kwargs)

    def filter(self, qs, value):
        if value is None or len(value) != 1:
            return qs

        value = value[0]
        if value == 'closed':
            return qs.closed()
        if value == 'new':
            return qs.new()

        return qs.open()


class RoundsFilter(filters.FilterSet):
    fund = Select2ModelMultipleChoiceFilter(queryset=get_used_funds, label='Funds')
    lead = Select2ModelMultipleChoiceFilter(queryset=get_round_leads, label='Leads')
    active = ActiveRoundFilter(label='Active')
    round_state = OpenRoundFilter(label='Open')


class LeaderboardFilterForm(forms.ModelForm):
    """
    Form to "clean" a list of User objects to their PKs.

    The Leaderboard table is a list of User objects, however we also want the
    ability to filter down to N Users (reviewers).  Django filter is converting
    the selected PKs to User objects, however we can't filter a User QuerySet
    with User objects.  So this form converts back to a list of User PKs using
    the clean_reviewer method.
    """
    class Meta:
        fields = ["id"]
        model = User

    def clean_reviewer(self):
        return [u.id for u in self.cleaned_data['reviewer']]


class LeaderboardFilter(filters.FilterSet):
    reviewer = Select2ModelMultipleChoiceFilter(
        field_name='pk',
        label='Reviewers',
        queryset=get_reviewers,
    )
    funds = Select2ModelMultipleChoiceFilter(
        field_name='submission__page',
        label='Funds',
        queryset=get_used_funds,
    )
    rounds = Select2ModelMultipleChoiceFilter(
        field_name='submission__round',
        label='Rounds',
        queryset=get_used_rounds,
    )

    class Meta:
        fields = [
            'reviewer',
            'funds',
            'rounds',
        ]
        form = LeaderboardFilterForm
        model = User


class LeaderboardTable(tables.Table):
    full_name = tables.Column(verbose_name="Reviewer")
    most_recent = tables.Column(orderable=False)

    class Meta:
        fields = [
            'full_name',
            'total',
            'ninety_days',
            'this_year',
            'last_year',
            'most_recent',
        ]
        model = User
        order_by = ('-total',)

    def render_most_recent(self, record):
        review = (Review.objects.filter(author__reviewer=record)
                                .order_by('-created_at')
                                .first())

        if review is None:
            return None

        return format_html(
            '<a href="{}">{}</a>',
            review.revision.submission.get_absolute_url(),
            review.revision.submission.title,
        )
