from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .forms import SignUpForm
from .models import User


def signup(request):
    if request.user.is_authenticated:
        return redirect("pulse:feed")
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            send_activation_email(request, user)
            return render(request, "accounts/check_email.html", {"email": user.email})
    else:
        form = SignUpForm()
    return render(request, "accounts/signup.html", {"form": form})


def send_activation_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = request.build_absolute_uri(reverse("accounts:activate", args=[uid, token]))
    send_mail(
        subject="Confirm your EUnited account",
        message=(
            f"Hi {user.display_name},\n\n"
            f"Confirm your EUnited account by opening this link:\n{link}\n\n"
            "If you didn't sign up, you can ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


def activate(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None
    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        login(request, user)
        messages.success(request, "Your account is confirmed. Welcome to EUnited!")
        return redirect("pulse:feed")
    messages.error(request, "This confirmation link is invalid or has expired.")
    return redirect("accounts:signup")
