from django import forms

from .models import Post, Tag


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%dT%H:%M")
        super().__init__(**kwargs)


class ClubPostForm(forms.ModelForm):
    """What a student club fills in to submit a post. It always goes to the review queue."""

    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.all(), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Post
        fields = (
            "club", "type", "title", "summary", "body", "image_url", "source_url", "language",
            "tags", "deadline", "event_start", "event_end", "location",
        )
        widgets = {
            "deadline": DateTimeInput(),
            "event_start": DateTimeInput(),
            "event_end": DateTimeInput(),
            "summary": forms.Textarea(attrs={"rows": 2}),
            "body": forms.Textarea(attrs={"rows": 8}),
        }
        labels = {"source_url": "Link (optional)", "image_url": "Image URL (optional)"}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["club"].queryset = user.clubs.filter(verified=True) if user else self.fields["club"].queryset.none()
        self.fields["club"].required = True
        self.fields["club"].empty_label = None
        for name in ("deadline", "event_start", "event_end"):
            self.fields[name].input_formats = ["%Y-%m-%dT%H:%M"]

    def save(self, commit=True):
        post = super().save(commit=False)
        post.author = self.user
        post.university = post.club.university
        post.status = Post.Status.PENDING
        if commit:
            post.save()
            self.save_m2m()
        return post

    def _post_clean(self):
        # university is set from the club, so fill it in before model validation runs
        if self.cleaned_data.get("club"):
            self.instance.university = self.cleaned_data["club"].university
        super()._post_clean()
