from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Sum, Count
from .models import AppUsage, AFKEvent
from .serializers import AppUsageSerializer, AFKEventSerializer
from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import IsAuthenticated
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
def org_summary(request):
    users = User.objects.all()
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
def user_detail(request, user_id):
    user = User.objects.get(id=user_id)

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
@permission_classes([IsAuthenticated])  # optional if token-based
def app_usage_summary(request):
    usage = filter_time_range(AppUsage.objects.all(), request)

    summarized = usage.values('app_name', 'productivity_tag').annotate(
        total_time=Sum('duration'),
        user_count=Count('user', distinct=True)
    ).order_by('-total_time')

    return Response(list(summarized))


@api_view(['POST'])
@permission_classes([IsAuthenticated])  # optional if token-based
def sync_activity_data(request):
    user = User.objects.get(email=request.data['email'])

    # Process window events
    for event in request.data.get('window_events', []):
        AppUsage.objects.update_or_create(
            user=user,
            start_time=event['timestamp'],
            defaults={
                'duration': event['duration'],
                'app_name': event['data']['app'],
                'window_title': event['data'].get('title', ''),
                'productivity_tag': tag_productivity(event['data']['app'])  # simple classifier
            }
        )

    # Process AFK events
    for event in request.data.get('afk_events', []):
        AFKEvent.objects.update_or_create(
            user=user,
            start_time=event['timestamp'],
            defaults={
                'duration': event['duration'],
                'is_afk': event['data']['status'] == 'afk'
            }
        )

    return Response({"status": "success"})

