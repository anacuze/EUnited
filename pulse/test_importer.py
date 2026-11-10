from io import StringIO
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import University, User

from . import importer
from .models import Post, Source

FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>UNICAL</title><link>https://www.unical.it</link><language>it</language>
  <item>
    <title>Seconda notizia &amp; altro</title>
    <link>http://www.unical.it/contents/news/view/2-seconda/</link>
    <description>Riassunto della seconda notizia.</description>
    <content:encoded><![CDATA[<p>Primo <strong>paragrafo</strong>.</p>
      <p><img src="/media/foto.jpg">Secondo paragrafo.</p>]]></content:encoded>
  </item>
  <item>
    <title>Prima notizia</title>
    <link>http://www.unical.it/contents/news/view/1-prima/</link>
    <description>&lt;p&gt;Riassunto con &lt;b&gt;HTML&lt;/b&gt;.&lt;/p&gt;</description>
  </item>
</channel></rss>"""

LISTING = b"""<html lang="hr"><body>
  <nav><a href="/o-sveucilistu">O nama</a><a href="/objave/novosti">Novosti</a></nav>
  <a href="/objave/novosti/prva-vijest/">Prva</a>
  <a href="/objave/novosti/prva-vijest/#komentari">Prva (again)</a>
  <a href="https://www.sum.ba/objave/novosti/druga-vijest">Druga</a>
  <a href="https://example.com/objave/novosti/tuda-vijest">Other site</a>
  <a href="mailto:info@sum.ba">Mail</a>
</body></html>"""

ARTICLE = """<html lang="hr"><head>
  <title>{title} | SUM</title>
  <meta property="og:title" content="{title} – SUM">
  <meta property="og:site_name" content="SUM">
  <meta property="og:description" content="Kratki opis vijesti.">
  <meta property="og:image" content="/storage/slika.jpg">
</head><body><main><h1>{title}</h1><p>Prvi odlomak.</p><p>Drugi odlomak.</p></main></body></html>"""


def fake_fetch(pages):
    """Stands in for importer.fetch: serves the given pages and fails on anything else."""
    def fetch(url):
        if url not in pages:
            raise importer.ImporterError(f"Could not open {url}: 404")
        return pages[url]
    return fetch


class ImporterTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sum = University.objects.create(short_name="SUM", name="University of Mostar")
        cls.unical = University.objects.create(short_name="UNICAL", name="University of Calabria")
        cls.feed = Source.objects.create(
            name="UNICAL news", url="https://www.unical.it/contents/news/rss",
            kind=Source.Kind.RSS, language="it", university=cls.unical,
        )
        cls.listing = Source.objects.create(
            name="SUM news", url="https://www.sum.ba/objave/novosti",
            kind=Source.Kind.SCRAPE, language="hr", university=cls.sum,
        )
        cls.pages = {
            cls.feed.url: FEED,
            cls.listing.url: LISTING,
            "https://www.sum.ba/objave/novosti/prva-vijest/": ARTICLE.format(title="Prva vijest").encode(),
            "https://www.sum.ba/objave/novosti/druga-vijest": ARTICLE.format(title="Druga vijest").encode(),
        }

    def setUp(self):
        patcher = mock.patch.object(importer, "fetch", side_effect=fake_fetch(self.pages))
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)


class FeedImportTests(ImporterTestCase):
    def test_feed_items_become_draft_news(self):
        result = importer.import_source(self.feed)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.created), 2)
        post = Post.objects.get(source_url="https://www.unical.it/contents/news/view/2-seconda/")
        self.assertEqual(post.title, "Seconda notizia & altro")
        self.assertEqual(post.summary, "Riassunto della seconda notizia.")
        self.assertEqual(post.body, "Primo paragrafo.\n\nSecondo paragrafo.")
        self.assertEqual(post.image_url, "https://www.unical.it/media/foto.jpg")
        self.assertEqual((post.type, post.status, post.language), ("news", "draft", "it"))
        self.assertEqual((post.source, post.university), (self.feed, self.unical))
        self.assertIsNone(post.published_at)
        other = Post.objects.get(source_url="https://www.unical.it/contents/news/view/1-prima/")
        self.assertEqual(other.summary, "Riassunto con HTML.")
        self.feed.refresh_from_db()
        self.assertIsNotNone(self.feed.last_checked_at)

    def test_imported_posts_stay_out_of_the_feed(self):
        importer.import_source(self.feed)
        self.assertNotContains(self.client.get(reverse("pulse:feed")), "Prima notizia")

    def test_second_run_adds_nothing(self):
        importer.import_source(self.feed)
        Post.objects.update(status=Post.Status.REJECTED)  # rejected posts must not come back
        result = importer.import_source(self.feed)
        self.assertEqual(result.created, [])
        self.assertEqual(Post.objects.count(), 2)

    def test_oldest_item_is_saved_first(self):
        importer.import_source(self.feed)
        titles = list(Post.objects.order_by("pk").values_list("title", flat=True))
        self.assertEqual(titles, ["Prima notizia", "Seconda notizia & altro"])

    def test_limit_takes_the_newest(self):
        result = importer.import_source(self.feed, limit=1)
        self.assertEqual([p.title for p in result.created], ["Seconda notizia & altro"])

    def test_dry_run_saves_nothing(self):
        result = importer.import_source(self.feed, dry_run=True)
        self.assertEqual(len(result.created), 2)
        self.assertEqual(Post.objects.count(), 0)
        self.feed.refresh_from_db()
        self.assertIsNone(self.feed.last_checked_at)

    def test_page_that_is_not_a_feed_is_reported(self):
        self.pages = {**self.pages, self.feed.url: b"<html><body>Not found</body></html>"}
        self.fetch.side_effect = fake_fetch(self.pages)
        result = importer.import_source(self.feed)
        self.assertTrue(result.failed)
        self.assertEqual(Post.objects.count(), 0)

    def test_long_text_is_shortened(self):
        self.assertEqual(importer.shorten("word " * 200, 500)[-1], "…")
        self.assertLessEqual(len(importer.shorten("word " * 200, 500)), 500)
        self.assertEqual(importer.shorten("  short   text ", 500), "short text")


class ScrapeImportTests(ImporterTestCase):
    def test_follows_only_news_links_of_the_same_site(self):
        result = importer.import_source(self.listing)
        self.assertEqual(result.errors, [])
        self.assertEqual(
            sorted(Post.objects.values_list("source_url", flat=True)),
            ["https://www.sum.ba/objave/novosti/druga-vijest",
             "https://www.sum.ba/objave/novosti/prva-vijest/"],
        )
        post = Post.objects.get(title="Prva vijest")
        self.assertEqual(post.summary, "Kratki opis vijesti.")
        self.assertEqual(post.body, "Prvi odlomak.\n\nDrugi odlomak.")
        self.assertEqual(post.image_url, "https://www.sum.ba/storage/slika.jpg")
        self.assertEqual((post.language, post.status), ("hr", "draft"))

    def test_site_name_is_removed_from_the_title(self):
        page = b"""<html><head><meta property="og:title" content="Big news | EUPeace">
            <meta property="og:site_name" content="EUPeace"></head><body></body></html>"""
        item = importer.read_article(self.listing, "https://www.sum.ba/x", page)
        self.assertEqual(item.title, "Big news")

    def test_link_pattern_chooses_the_links(self):
        self.listing.link_pattern = r"/novosti/druga-"
        self.listing.save()
        importer.import_source(self.listing)
        self.assertEqual(list(Post.objects.values_list("title", flat=True)), ["Druga vijest"])

    def test_known_pages_are_not_downloaded_again(self):
        importer.import_source(self.listing)
        self.fetch.reset_mock()
        importer.import_source(self.listing)
        self.fetch.assert_called_once_with(self.listing.url)

    def test_one_broken_page_does_not_stop_the_rest(self):
        pages = dict(self.pages)
        del pages["https://www.sum.ba/objave/novosti/prva-vijest/"]
        self.fetch.side_effect = fake_fetch(pages)
        result = importer.import_source(self.listing)
        self.assertEqual([p.title for p in result.created], ["Druga vijest"])
        self.assertEqual(len(result.errors), 1)
        self.assertFalse(result.failed)

    def test_listing_without_links_is_reported(self):
        self.fetch.side_effect = fake_fetch({self.listing.url: b"<html><body><div id='app'></div></body></html>"})
        result = importer.import_source(self.listing)
        self.assertTrue(result.failed)
        self.assertIn("No news links found", result.errors[0])

    def test_bad_link_pattern_is_refused(self):
        self.listing.link_pattern = "([unclosed"
        with self.assertRaises(ValidationError):
            self.listing.full_clean()


class ImportCommandTests(ImporterTestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command("import_posts", *args, stdout=out)
        return out.getvalue()

    def test_imports_from_every_active_source(self):
        unreachable = Source.objects.create(
            name="Broken", url="https://broken.example/feed", kind=Source.Kind.RSS, university=self.sum)
        Source.objects.create(
            name="Switched off", url="https://off.example/feed", kind=Source.Kind.RSS,
            university=self.sum, active=False)
        output = self.run_command()
        self.assertEqual(Post.objects.count(), 4)
        self.assertIn("4 post(s) imported", output)
        self.assertIn("Could not open https://broken.example/feed", output)
        self.assertNotIn("Switched off", output)
        unreachable.refresh_from_db()
        self.assertIsNotNone(unreachable.last_checked_at)

    def test_source_option_and_dry_run(self):
        output = self.run_command("--source", "unical", "--dry-run")
        self.assertIn("Prima notizia", output)
        self.assertIn("2 post(s) would be imported", output)
        self.assertEqual(Post.objects.count(), 0)

    def test_admin_action_imports(self):
        admin = User.objects.create_superuser("admin@sum.ba", "pass12345!")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("admin:pulse_source_changelist"),
            {"action": "import_now", "_selected_action": [self.feed.pk]}, follow=True,
        )
        self.assertContains(response, "2 new post(s) added to the Review queue")
        self.assertEqual(Post.objects.count(), 2)
