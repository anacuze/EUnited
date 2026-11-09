import re

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import University, User


class SignUpTests(TestCase):
    def setUp(self):
        University.objects.create(short_name="SUM", name="University of Mostar", email_domain="sum.ba")

    def signup(self, email):
        return self.client.post(reverse("accounts:signup"), {
            "first_name": "Ana", "last_name": "C", "email": email,
            "password1": "a-good-pass-123", "password2": "a-good-pass-123",
        })

    def test_non_university_email_rejected(self):
        response = self.signup("someone@gmail.com")
        self.assertContains(response, "Please use your university email")
        self.assertFalse(User.objects.exists())

    def test_signup_and_confirm(self):
        self.signup("ana@sum.ba")
        user = User.objects.get(email="ana@sum.ba")
        self.assertFalse(user.is_active)
        self.assertEqual(user.university.short_name, "SUM")
        link = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        self.client.get(link)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_subdomain_email_accepted(self):
        self.signup("ana@fpmoz.sum.ba")
        self.assertTrue(User.objects.filter(email="ana@fpmoz.sum.ba").exists())

    def test_login_with_email(self):
        User.objects.create_user("luca@sum.ba", "a-good-pass-123")
        ok = self.client.login(username="luca@sum.ba", password="a-good-pass-123")
        self.assertTrue(ok)
