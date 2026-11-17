from django.urls import path

from . import views

app_name = "pulse"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("archive/", views.archive, name="archive"),
    path("post/<int:pk>/", views.post_detail, name="post_detail"),
    path("post/<int:pk>/like/", views.like, name="like"),
    path("post/<int:pk>/follow/", views.follow, name="follow"),
    path("post/<int:pk>/comment/", views.comment_add, name="comment_add"),
    path("comment/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("comment/<int:pk>/report/", views.comment_report, name="comment_report"),
    path("comment/<int:pk>/moderate/", views.comment_moderate, name="comment_moderate"),
    path("rules/", views.rules, name="rules"),
    path("notifications/", views.notifications, name="notifications"),
    path("submit/", views.club_submissions, name="club_submissions"),
]
