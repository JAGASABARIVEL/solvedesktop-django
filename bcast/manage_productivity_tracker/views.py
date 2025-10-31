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


# views.py
from datetime import timedelta, datetime
import math
from django.db.models import Sum
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_404_NOT_FOUND, HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS

from .models import AppUsage, AFKEvent
from .serializers import AppUsageSerializer, AFKEventSerializer

# reuse your filter_time_range function
def get_bucket_seconds(granularity: str) -> int:
    if granularity == "hour":
        return 3600
    if granularity == "day":
        return 86400
    return 60  # minute default

def floor_to_bucket(dt: datetime, bucket_seconds: int) -> datetime:
    ts = int(dt.timestamp())
    floored = ts - (ts % bucket_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_detail(request, user_id):
    # AUTH CHECKS (same as yours)
    request_user = request.user
    if not request_user.is_productivity_enable or request_user.user_type != "owner":
        return Response({"error": "Not authorized"}, status=HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS)

    user_org = request_user.enterprise_profile.organization
    try:
        user = User.objects.get(id=user_id, enterprise_profile__organization=user_org)
    except User.DoesNotExist:
        return Response({"error": "User not found or access denied"}, status=HTTP_404_NOT_FOUND)

    # PARAMS
    summary_only = request.GET.get("summary", "false").lower() == "true"
    granularity = request.GET.get("granularity", "minute")  # minute|hour|day
    top_n = int(request.GET.get("top_n", 5))
    bucket_seconds = get_bucket_seconds(granularity)

    # Filter event querysets by start/end using your util
    usage_qs = filter_time_range(AppUsage.objects.filter(user=user).order_by("start_time"), request)
    afk_qs = filter_time_range(AFKEvent.objects.filter(user=user).order_by("start_time"), request)

    # SUMMARY totals
    productive = usage_qs.filter(productivity_tag="productive").aggregate(Sum("duration"))["duration__sum"] or 0
    unproductive = usage_qs.filter(productivity_tag="unproductive").aggregate(Sum("duration"))["duration__sum"] or 0
    neutral = usage_qs.filter(productivity_tag="neutral").aggregate(Sum("duration"))["duration__sum"] or 0
    afk_time = afk_qs.filter(is_afk=True).aggregate(Sum("duration"))["duration__sum"] or 0

    summary = {
        "user": user.username,
        "productive_minutes": round(productive / 60, 2),
        "unproductive_minutes": round(unproductive / 60, 2),
        "neutral_minutes": round(neutral / 60, 2),
        "afk_minutes": round(afk_time / 60, 2),
    }

    if summary_only:
        return Response({"summary": summary})

    # If no events, return empty timeline
    if not usage_qs.exists() and not afk_qs.exists():
        return Response({
            "summary": summary,
            "timeline": [],
            "top_apps": []
        })

    # Determine start/end (limit to requested start/end if provided by filter_time_range)
    # safe retrieval of earliest/latest
    start_candidates = []
    end_candidates = []
    if usage_qs.exists():
        start_candidates.append(usage_qs.earliest("start_time").start_time)
        # compute end_time if you have end_time field else start_time + duration
        if hasattr(usage_qs.model, "end_time"):
            end_candidates.append(usage_qs.latest("end_time").end_time)
        else:
            # compute from start + duration
            last = usage_qs.order_by("-start_time").first()
            end_candidates.append(last.start_time + timedelta(seconds=last.duration))
    if afk_qs.exists():
        start_candidates.append(afk_qs.earliest("start_time").start_time)
        if hasattr(afk_qs.model, "end_time"):
            end_candidates.append(afk_qs.latest("end_time").end_time)
        else:
            last = afk_qs.order_by("-start_time").first()
            end_candidates.append(last.start_time + timedelta(seconds=last.duration))

    start = min(start_candidates)
    end = max(end_candidates)

    # Align start/end to bucket boundaries
    start_bucket = floor_to_bucket(start, bucket_seconds)
    end_bucket = floor_to_bucket(end + timedelta(seconds=bucket_seconds), bucket_seconds)  # inclusive

    total_seconds = int((end_bucket - start_bucket).total_seconds())
    bucket_count = math.ceil(total_seconds / bucket_seconds)
    # Safety clamp for extremely large ranges
    MAX_BUCKETS = 24 * 60 if granularity == "minute" else 24 * 7
    if bucket_count > 50000:  # arbitrary safety
        return Response({"error": "Requested time range too large"}, status=400)

    # build empty buckets
    # buckets: list of dicts holding sums (seconds) and flags
    buckets = [
        {
            "time": (start_bucket + timedelta(seconds=i * bucket_seconds)).isoformat(),
            "productive_seconds": 0,
            "unproductive_seconds": 0,
            "neutral_seconds": 0,
            "afk_seconds": 0
        } for i in range(bucket_count)
    ]

    # helper to fill buckets for interval events
    def fill_event_in_buckets(event_start_dt, duration_seconds, tag=None, is_afk=False):
        if duration_seconds <= 0:
            return
        event_start_ts = int(event_start_dt.timestamp())
        event_end_ts = event_start_ts + int(duration_seconds)
        # compute indices
        start_idx = (event_start_ts - int(start_bucket.timestamp())) // bucket_seconds
        end_idx = (event_end_ts - int(start_bucket.timestamp())) // bucket_seconds
        # clamp
        start_idx = max(0, start_idx)
        end_idx = min(bucket_count - 1, end_idx)
        # if event fits within a few buckets, distribute overlap
        for idx in range(start_idx, end_idx + 1):
            bucket_start_ts = int(start_bucket.timestamp()) + idx * bucket_seconds
            bucket_end_ts = bucket_start_ts + bucket_seconds
            overlap_start = max(event_start_ts, bucket_start_ts)
            overlap_end = min(event_end_ts, bucket_end_ts)
            overlap = max(0, overlap_end - overlap_start)
            if overlap <= 0:
                continue
            if is_afk:
                buckets[idx]["afk_seconds"] += overlap
            else:
                if tag == "productive":
                    buckets[idx]["productive_seconds"] += overlap
                elif tag == "unproductive":
                    buckets[idx]["unproductive_seconds"] += overlap
                else:
                    buckets[idx]["neutral_seconds"] += overlap

    # Stream events from DB, convert to buckets. Use iterator() to avoid high mem.
    # For AppUsage, we expect fields: start_time (datetime), duration (int), productivity_tag
    for u in usage_qs.iterator():
        # calculate start_time and duration (seconds)
        u_start = u.start_time
        u_dur = int(u.duration or 0)
        u_tag = getattr(u, "productivity_tag", None)
        fill_event_in_buckets(u_start, u_dur, tag=u_tag, is_afk=False)

    # AFK events
    for a in afk_qs.iterator():
        a_start = a.start_time
        a_dur = int(a.duration or 0)
        # consider only is_afk true as idle
        fill_event_in_buckets(a_start, a_dur, tag=None, is_afk=True)

    # Prepare timeline array, convert seconds to minutes for UI convenience
    timeline = []
    for b in buckets:
        # skip empty buckets optionally
        timeline.append({
            "time": b["time"],
            "productive_minutes": round(b["productive_seconds"] / 60, 2),
            "unproductive_minutes": round(b["unproductive_seconds"] / 60, 2),
            "neutral_minutes": round(b["neutral_seconds"] / 60, 2),
            "afk_minutes": round(b["afk_seconds"] / 60, 2)
        })

    # Top apps: aggregate total duration per (app_name, window_title)
    # Do this on DB using values + annotate for efficiency
    top_apps_qs = usage_qs.values("app_name", "window_title").annotate(total=Sum("duration")).order_by("-total")[:top_n]
    top_apps = [
        {"app_name": r["app_name"], "window_title": r["window_title"], "total_minutes": round((r["total"] or 0) / 60, 2)}
        for r in top_apps_qs
    ]

    return Response({
        "summary": summary,
        "timeline": timeline,
        "top_apps": top_apps,
    })




from django.http import StreamingHttpResponse, JsonResponse
from django.db.models import Sum
import json

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_detail_stream(request, user_id):
    request_user = request.user
    if not request_user.is_productivity_enable or request_user.user_type != 'owner':
        return Response(
            {"error": "Not authorized"},
            status=HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS
        )

    user_org = request_user.enterprise_profile.organization
    try:
        user = User.objects.get(id=user_id, enterprise_profile__organization=user_org)
    except User.DoesNotExist:
        return Response({"error": "User not found"}, status=HTTP_404_NOT_FOUND)

    usage = filter_time_range(AppUsage.objects.filter(user=user), request)
    afk = filter_time_range(AFKEvent.objects.filter(user=user), request)

    productive = usage.filter(productivity_tag='productive').aggregate(Sum('duration'))['duration__sum'] or 0
    unproductive = usage.filter(productivity_tag='unproductive').aggregate(Sum('duration'))['duration__sum'] or 0
    neutral = usage.filter(productivity_tag='neutral').aggregate(Sum('duration'))['duration__sum'] or 0
    afk_time = afk.filter(is_afk=True).aggregate(Sum('duration'))['duration__sum'] or 0

    # Step 1: Send small summary as normal JSON
    summary = {
        'user': user.username,
        'productive_minutes': round(productive / 60, 2),
        'unproductive_minutes': round(unproductive / 60, 2),
        'neutral_minutes': round(neutral / 60, 2),
        'afk_minutes': round(afk_time / 60, 2),
    }

    def row_generator():
        yield json.dumps({"summary": summary}) + "\n"
        yield json.dumps({"app_usage": "start"}) + "\n"

        for row in usage.iterator():
            yield json.dumps(AppUsageSerializer(row).data) + "\n"

        yield json.dumps({"app_usage": "end"}) + "\n"
        yield json.dumps({"afk_events": "start"}) + "\n"

        for row in afk.iterator():
            yield json.dumps(AFKEventSerializer(row).data) + "\n"

        yield json.dumps({"afk_events": "end"}) + "\n"

    return StreamingHttpResponse(row_generator(), content_type="application/x-ndjson")



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


