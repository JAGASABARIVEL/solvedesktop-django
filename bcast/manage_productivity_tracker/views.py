from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Sum, Count
from .models import AppUsage, AFKEvent
from .serializers import AppUsageSerializer, AFKEventSerializer
from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import IsAuthenticated
from rest_framework.status import HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS, HTTP_404_NOT_FOUND
from rest_framework.decorators import permission_classes

User = get_user_model()


def tag_productivity(app_name):
    productive = ["code", "terminal", "browser", "slack", "notion"]
    unproductive = ["youtube", "netflix", "spotify", "games"]
    app = app_name.lower()

    if any(p in app for p in productive):
        return "productive"
    elif any(p in app for p in unproductive):
        return "unproductive"
    return "neutral"


def filter_time_range(queryset, request):
    start = parse_datetime(request.GET.get("start") or "")
    end = parse_datetime(request.GET.get("end") or "")
    if start:
        queryset = queryset.filter(start_time__gte=start)
    if end:
        queryset = queryset.filter(start_time__lte=end)
    return queryset

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_summary(request):
    request_user = request.user
    # Check if user is allowed
    if not request_user.is_productivity_enable:
        return Response({"error": "Not authorized to access this application"}, status=HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS)
    # Get the organization of the requesting user
    user_org = request_user.enterprise_profile.organization
    app_qs = filter_time_range(AppUsage.objects.filter(user=request_user), request)
    afk_qs = filter_time_range(AFKEvent.objects.filter(user=request_user), request)
    total_active = app_qs.aggregate(total=Sum('duration'))['total'] or 0
    total_afk = afk_qs.filter(is_afk=True).aggregate(total=Sum('duration'))['total'] or 0
    total_logged = total_active + total_afk
    productivity_score = (total_active / total_logged) * 100 if total_logged else 0
    result = {
        'user': request_user.username,
        'productive_time_seconds': total_active,
        'afk_time_seconds': total_afk,
        'score': round(productivity_score, 1)
    }
    return Response(result)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def org_summary(request):
    request_user = request.user
    # Check if user is allowed
    if not request_user.is_productivity_enable or request_user.user_type != 'owner':
        return Response({"error": "Not authorized to access this application"}, status=HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS)
    # Get the organization of the requesting user
    user_org = request_user.enterprise_profile.organization
    # Filter users by organization
    users = User.objects.filter(enterprise_profile__organization=user_org)
    result = []
    for user in users:
        app_qs = filter_time_range(AppUsage.objects.filter(user=user), request)
        afk_qs = filter_time_range(AFKEvent.objects.filter(user=user), request)
        total_active = app_qs.aggregate(total=Sum('duration'))['total'] or 0
        total_afk = afk_qs.filter(is_afk=True).aggregate(total=Sum('duration'))['total'] or 0
        total_logged = total_active + total_afk
        productivity_score = (total_active / total_logged) * 100 if total_logged else 0
        result.append({
            'user': user.username,
            'productive_time_minutes': round(total_active / 60, 2),
            'afk_time_minutes': round(total_afk / 60, 2),
            'score': round(productivity_score, 1)
        })
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_detail(request, user_id):
    request_user = request.user
    if not request_user.is_productivity_enable  or request_user.user_type != 'owner':
        return Response({"error": "Not authorized to access this application"}, status=HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS)
    user_org = request_user.enterprise_profile.organization
    try:
        # Fetch the user and ensure they belong to the same organization
        user = User.objects.get(id=user_id, enterprise_profile__organization=user_org)
    except User.DoesNotExist:
        return Response({"error": "User not found or access denied"}, status=HTTP_404_NOT_FOUND)

    usage = filter_time_range(AppUsage.objects.filter(user=user), request)
    afk = filter_time_range(AFKEvent.objects.filter(user=user), request)
    productive = usage.filter(productivity_tag='productive').aggregate(Sum('duration'))['duration__sum'] or 0
    unproductive = usage.filter(productivity_tag='unproductive').aggregate(Sum('duration'))['duration__sum'] or 0
    neutral = usage.filter(productivity_tag='neutral').aggregate(Sum('duration'))['duration__sum'] or 0
    afk_time = afk.filter(is_afk=True).aggregate(Sum('duration'))['duration__sum'] or 0
    return Response({
        'user': user.username,
        'productive_minutes': round(productive / 60, 2),
        'unproductive_minutes': round(unproductive / 60, 2),
        'neutral_minutes': round(neutral / 60, 2),
        'afk_minutes': round(afk_time / 60, 2),
        'app_usage': AppUsageSerializer(usage, many=True).data,
        'afk_events': AFKEventSerializer(afk, many=True).data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def app_usage_summary(request):
    request_user = request.user
    # Check if user is allowed
    if not request_user.is_productivity_enable  or request_user.user_type != 'owner':
        return Response({"error": "Not authorized to access this application"}, status=HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS)
    # Get organization users
    user_org = request_user.enterprise_profile.organization
    org_users = User.objects.filter(enterprise_profile__organization=user_org)
    # Filter AppUsage by users in the same organization
    usage = filter_time_range(AppUsage.objects.filter(user__in=org_users), request)
    # Aggregate results
    summarized = usage.values('app_name', 'productivity_tag').annotate(
        total_time=Sum('duration'),
        user_count=Count('user', distinct=True)
    ).order_by('-total_time')
    return Response(list(summarized))


from dateutil.parser import parse
from django.db import transaction


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def sync_activity_data(request):
    user = User.objects.get(email=request.data['email'])
    system = request.data.get('system', 'default')
    # Process window (app usage) events
    window_events = sorted(request.data.get('window_events', []), key=lambda e: int(e['id']))
    for event in window_events:
        start_time = parse(event['timestamp'])
        AppUsage.objects.update_or_create(
            user=user,
            system=system,
            event_id=event['id'],
            defaults={
                'start_time': start_time,
                'duration': event['duration'],
                'app_name': event['data']['app'],
                'window_title': event['data'].get('title', ''),
                'productivity_tag': tag_productivity(event['data']['app']),
            }
        )
    # Process AFK events
    afk_events = sorted(request.data.get('afk_events', []), key=lambda e: int(e['id']))
    for event in afk_events:
        event_id = event['id']
        start_time = parse(event['timestamp'])
        duration = event['duration']
        is_afk = event['data']['status'] == 'afk'
        # Step 1: Avoid duplicates entirely
        if AFKEvent.objects.filter(user=user, system=system, event_id=event_id).exists():
            continue  # Skip duplicate event_id
        # Step 2: Get last event for this user/system
        last_event = AFKEvent.objects.filter(user=user, system=system).order_by('-event_id').first()
        if is_afk:
            if last_event and last_event.is_afk:
                # Already in afk state — don’t insert another afk row
                continue
        else:
            if last_event and last_event.is_afk:
                # End previous AFK session
                last_event.duration = (start_time - last_event.start_time).total_seconds()
                last_event.save()
        AFKEvent.objects.update_or_create(
            user=user,
            system=system,
            event_id=event_id,
            defaults={
                'start_time': start_time,
                'duration': duration,
                'is_afk': is_afk,
            }
        )
    return Response({"status": "success"})

