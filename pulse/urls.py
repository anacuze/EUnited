from django.urls import path

from . import views

app_name = "pulse"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("archive/", views.archive, name="archive"),
    path("post/<int:pk>/", views.post_detail, name="post_detail"),
    path("post/<int:pk>/like/", views.like, name="like"),
    path("post/<int:pk>/follow/", views.follow, name="follow"),
    path("notifications/", views.notifications, name="notifications"),
    path("submit/", views.club_submissions, name="club_submissions"),
]
