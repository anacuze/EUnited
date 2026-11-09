from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models


class University(models.Model):
    """A university (or the EUPeace alliance itself) that students and posts belong to."""

    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=20, unique=True, help_text="e.g. SUM, UNICAL")
    email_domain = models.CharField(
        max_length=100,
        blank=True,
        help_text="Students with this email domain can sign up, e.g. sum.ba. "
        "Leave empty if sign-up is not allowed for this university.",
    )
    website = models.URLField(blank=True)

    class Meta:
        ordering = ["short_name"]
        verbose_name_plural = "universities"

    def __str__(self):
        return self.short_name


class UserManager(BaseUserManager):
    """Users log in with their email address instead of a username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.STUDENT)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields["role"] = User.Role.SUPERADMIN
        return self._create_user(email, password, **extra_fields)


def domain_of(email):
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPERADMIN = "superadmin", "Superadmin"
        EDITOR = "editor", "Editor"
        MODERATOR = "moderator", "Moderator"
        CLUB = "club", "Student club"
        STUDENT = "student", "Student"

    username = None
    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    university = models.ForeignKey(
        University, null=True, blank=True, on_delete=models.SET_NULL, related_name="users"
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def save(self, *args, **kwargs):
        # Keep Django's built-in flags in sync with the EUnited role.
        self.is_superuser = self.role == self.Role.SUPERADMIN
        self.is_staff = self.role in (self.Role.SUPERADMIN, self.Role.EDITOR, self.Role.MODERATOR)
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.email.split("@")[0]

    @property
    def is_club_account(self):
        return self.role == self.Role.CLUB

    @property
    def can_submit_posts(self):
        """Members of a verified student club can submit posts for approval."""
        return self.clubs.filter(verified=True).exists()

    def __str__(self):
        return self.email


class Club(models.Model):
    """A verified student association (e.g. SWITCH) that can submit posts for approval."""

    name = models.CharField(max_length=200)
    university = models.ForeignKey(University, on_delete=models.PROTECT, related_name="clubs")
    contact_email = models.EmailField(blank=True)
    description = models.TextField(blank=True)
    verified = models.BooleanField(
        default=False, help_text="Only verified clubs can submit posts."
    )
    members = models.ManyToManyField(User, blank=True, related_name="clubs")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.university})"

    def clean(self):
        if self.contact_email and "@" not in self.contact_email:
            raise ValidationError({"contact_email": "Enter a valid email address."})
