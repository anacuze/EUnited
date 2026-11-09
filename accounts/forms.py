from django import forms
from django.contrib.auth import forms as auth_forms

from .models import University, User, domain_of


class AdminUserCreationForm(auth_forms.UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "role", "university")


class AdminUserChangeForm(auth_forms.UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class SignUpForm(forms.ModelForm):
    """Student sign-up. Only university email domains listed on a University are accepted."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, min_length=8)
    password2 = forms.CharField(label="Repeat password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        help_texts = {"email": "Use your university email, e.g. name@sum.ba or name@unical.it."}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        domain = domain_of(email)
        university = University.objects.filter(email_domain__iexact=domain).first()
        if university is None:
            # Allow sub-domains such as student.sum.ba or fpmoz.sum.ba
            for uni in University.objects.exclude(email_domain=""):
                if domain.endswith("." + uni.email_domain.lower()):
                    university = uni
                    break
        if university is None:
            allowed = ", ".join(
                "@" + d for d in University.objects.exclude(email_domain="").values_list("email_domain", flat=True)
            )
            raise forms.ValidationError(
                f"Please use your university email. Allowed domains: {allowed or 'none configured yet'}."
            )
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        self.university = university
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") and cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "The passwords don't match.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.university = self.university
        user.role = User.Role.STUDENT
        user.is_active = False  # activated by the email confirmation link
        if commit:
            user.save()
        return user


class LoginForm(auth_forms.AuthenticationForm):
    username = forms.EmailField(label="University email", widget=forms.EmailInput(attrs={"autofocus": True}))
