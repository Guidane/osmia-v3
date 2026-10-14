"""The AI assistant's pages: ask, copy the prompt, paste the answer, check, make."""
from dataclasses import asdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import space as spaces
from core.models import App, Space
from core.permissions import can, can_space, visible_apps, visible_spaces

from . import plan as plans
from .models import Run
from .prompt import build

MAX_REQUEST = 5_000


def _scope(request, values):
    """The space, app and page the request is about, if the person may see them."""
    space = app = page = None
    if values.get('page'):
        try:
            from extensions.pages.models import Page
            page = Page.objects.select_related('space').filter(pk=int(values['page'])).first()
        except (ImportError, ValueError):
            page = None
        if page is not None and can_space(request.user, page.space, 'viewer'):
            space = page.space
        else:
            page = None
    if values.get('app'):
        app = App.objects.select_related('space').filter(slug=values['app']).first()
        if app is None or not can(request.user, app, 'viewer'):
            app = None
        elif space is None:
            space = app.space
    if values.get('space') and space is None:
        space = Space.objects.filter(key__iexact=values['space']).first()
        if space is not None and not can_space(request.user, space, 'viewer'):
            space = None
    return space, app, page


def _choices(user):
    own = spaces.ensure_personal(user)
    return {'spaces': [own] + [s for s in visible_spaces(user) if not s.is_personal],
            'apps': [a for a in visible_apps(user) if not a.is_space]}


@login_required
def index(request):
    if request.method == 'POST':
        text = request.POST.get('request', '').strip()
        if not text:
            messages.error(request, 'Write what you want first.')
            return redirect(request.get_full_path())
        space, app, page = _scope(request, request.POST)
        records = request.POST.get('records') == 'on'
        run = Run.objects.create(user=request.user, request=text[:MAX_REQUEST],
                                 scope={'space': space.key if space else '', 'app': app.slug if app else '',
                                        'page': page.pk if page else None, 'records': records},
                                 prompt=build(request.user, text[:MAX_REQUEST], space, app, page, records))
        return redirect(run)
    space, app, page = _scope(request, request.GET)
    return render(request, 'assistant/index.html', {
        **_choices(request.user), 'space': space, 'app': app, 'page': page,
        'runs': Run.objects.filter(user=request.user)[:15]})


def _run(request, pk):
    return get_object_or_404(Run, pk=pk, user=request.user)


@login_required
def run_view(request, pk):
    run = _run(request, pk)
    return render(request, 'assistant/run.html', {
        'run': run, 'fix': plans.fix_message([plans.Step(**s) for s in run.results], run.problem)
        if run.status == Run.Status.PROBLEMS else '',
        'failed': [s for s in run.results if s.get('error')]})


def _check(run, user):
    """Read and try out the answer; keeps what it found on ``run``."""
    run.results, run.problem, run.summary = [], '', ''
    try:
        plan = plans.parse(run.answer)
    except plans.PlanError as e:
        run.problem, run.status = str(e), Run.Status.PROBLEMS
        return None
    if plan.get('question') and not plan.get('changes'):
        run.problem, run.status = str(plan['question'])[:2000], Run.Status.QUESTION
        return None
    run.summary = str(plan.get('summary') or '')[:300]
    steps = plans.run(plan, user)
    run.results = [asdict(s) for s in steps]
    run.status = Run.Status.READY if all(s.ok for s in steps) else Run.Status.PROBLEMS
    return plan


@login_required
@require_POST
def check(request, pk):
    run = _run(request, pk)
    if run.status == Run.Status.DONE:
        messages.info(request, 'These changes are made already. Ask again for more.')
        return redirect(run)
    run.answer = request.POST.get('answer', '')[:plans.MAX_ANSWER + 1]
    _check(run, request.user)
    run.save()
    return redirect(run.get_absolute_url() + '#result')


@login_required
@require_POST
def apply(request, pk):
    run = _run(request, pk)
    if run.status != Run.Status.READY:
        messages.error(request, 'Check the answer first.')
        return redirect(run)
    plan = _check(run, request.user)   # again: the workspace may have changed since
    if plan is None or run.status != Run.Status.READY:
        run.save()
        messages.error(request, 'Something changed since the check; nothing was made. See the problems below.')
        return redirect(run.get_absolute_url() + '#result')
    steps = plans.run(plan, request.user, apply=True)
    run.results = [asdict(s) for s in steps]
    if all(s.ok for s in steps):
        run.status, run.applied_at = Run.Status.DONE, timezone.now()
        messages.success(request, f'Done: {len(steps)} change{"s" if len(steps) != 1 else ""} made.')
    else:
        run.status = Run.Status.PROBLEMS
        messages.error(request, 'One change didn\'t work, so nothing was made. See the problems below.')
    run.save()
    return redirect(run.get_absolute_url() + '#result')
