"""Offline structural fixtures: these are synthetic, not captured source pages."""

import unittest

import yaml

from pipeline.discovery.crawler import SUBJECTS_PATH
from pipeline.discovery.parser import evaluate_link, parse_html


CONFIG = yaml.safe_load(SUBJECTS_PATH.read_text(encoding="utf-8"))
SOURCE = {"name": "Fixture school", "language": "si"}
BASE = "https://school.test/"


class LocalEvidenceTests(unittest.TestCase):
    def evaluate(self, html):
        page = parse_html(html)
        return page, [evaluate_link(link, page.title, BASE, SOURCE, CONFIG) for link in page.links]

    def test_table_row_associates_text_before_and_after_link(self):
        for cells in (
            '<td>Grade 10 History past paper</td><td><a href="/download/123">Download</a></td>',
            '<td><a href="/download/123">Download</a></td><td>Grade 10 History past paper</td>',
        ):
            with self.subTest(cells=cells):
                page, [(candidate, decision)] = self.evaluate(f"<table><tr>{cells}</tr></table>")
                self.assertIsNotNone(candidate)
                self.assertEqual((candidate["subject"], candidate["grade"], candidate["document_type"]),
                                 ("History", "10", "past_paper"))
                self.assertIn("resource_local_evidence:tr", decision.reasons)
                self.assertEqual(page.links[0].before, "")

    def test_sibling_rows_do_not_share_subject_or_grade(self):
        _, decisions = self.evaluate('<table><tr><td>Grade 10 History past paper</td>'
            '<td><a href="/download/1">Download</a></td></tr>'
            '<tr><td>Grade 12 Chemistry marking scheme</td><td><a href="/download/2">Download</a></td></tr>'
            '<tr><td><a href="/download/3">Download</a></td></tr></table>')
        self.assertEqual((decisions[0][0]["subject"], decisions[0][0]["grade"]), ("History", "10"))
        self.assertEqual((decisions[1][0]["subject"], decisions[1][0]["grade"]), ("Chemistry", "12"))
        self.assertIsNone(decisions[2][0])

    def test_semantic_items_and_explicit_cards_supply_evidence(self):
        for tag, attrs in (("li", ""), ("article", ""), ("dd", ""), ("div", 'class="resource-card"')):
            _, [(candidate, _)] = self.evaluate(f'<{tag} {attrs}><h3>Grade 11 History teacher guide</h3>'
                                               f'<a href="/download/1">Open</a></{tag}>')
            self.assertEqual(candidate["document_type"], "teacher_guide")

    def test_sinhala_description_and_download_text(self):
        _, [(candidate, _)] = self.evaluate('<li>8 ශ්‍රේණිය ඉතිහාසය පෙළපොත '
                                           '<a href="/download/si">බාගත කරන්න</a></li>')
        self.assertEqual((candidate["subject"], candidate["grade"]), ("History", "8"))

    def test_multiple_destinations_are_ambiguous(self):
        page, decisions = self.evaluate('<div class="card">Grade 10 History past paper '
            '<a href="/download/1">Download</a> Grade 12 Chemistry marking scheme '
            '<a href="/download/2">Download</a></div>')
        self.assertTrue(all(not link.resource_context for link in page.links))
        self.assertTrue(all(candidate is None for candidate, _ in decisions))

    def test_nested_items_remain_separate(self):
        _, decisions = self.evaluate('<article><ul><li>Grade 10 History textbook '
            '<a href="/download/1">Download</a></li><li>Grade 12 Chemistry textbook '
            '<a href="/download/2">Download</a></li></ul></article>')
        self.assertEqual([candidate["subject"] for candidate, _ in decisions], ["History", "Chemistry"])

    def test_global_heading_and_unstructured_div_are_not_evidence(self):
        for html in ('<h1>Grade 10 History textbook</h1><a href="/opaque">Download</a>',
                     '<div>Grade 10 History textbook<a href="/opaque">Download</a></div>',
                     '<title>Grade 10 History textbook</title><li><a href="/opaque">Download</a></li>'):
            _, [(candidate, _)] = self.evaluate(html)
            self.assertIsNone(candidate)

    def test_navigation_hidden_and_footer_context_is_excluded(self):
        for tag, attrs in (("nav", ""), ("footer", ""), ("aside", ""),
                           ("div", 'role="navigation"'), ("div", "hidden"), ("div", 'aria-hidden="true"')):
            page, [(candidate, _)] = self.evaluate(f'<article><{tag} {attrs}>Grade 10 History textbook '
                f'<a href="/opaque">Download</a></{tag}></article>')
            self.assertEqual(page.links[0].resource_context, "")
            self.assertIsNone(candidate)

    def test_oversized_and_unclosed_scopes_are_not_evidence(self):
        for html in ('<article>Grade 10 History textbook ' + 'x ' * 300 +
                     '<a href="/opaque">Download</a></article>',
                     '<li>Grade 10 History textbook<a href="/opaque">Download</a>'):
            page, [(candidate, _)] = self.evaluate(html)
            self.assertEqual(page.links[0].resource_context, "")
            self.assertIsNone(candidate)

    def test_informative_anchor_and_title_attribute_take_precedence(self):
        _, [(candidate, _)] = self.evaluate('<li>Grade 10 History textbook '
            '<a href="/download/1">Grade 12 Chemistry marking scheme</a></li>')
        self.assertEqual((candidate["subject"], candidate["grade"]), ("Chemistry", "12"))
        _, [(candidate, _)] = self.evaluate('<li>Grade 10 History textbook '
            '<a href="/download/1" title="Grade 12 Chemistry marking scheme">Download</a></li>')
        self.assertEqual((candidate["subject"], candidate["grade"]), ("Chemistry", "12"))

    def test_category_and_login_routes_do_not_inherit_resource_identity(self):
        for path in ("/category/history", "/Paper", "/login", "/contact"):
            _, [(candidate, _)] = self.evaluate('<li>Grade 10 History textbook '
                                                f'<a href="{path}">Download</a></li>')
            self.assertIsNone(candidate)

    def test_ignored_nested_templates_cannot_leak_evidence(self):
        _, [(candidate, _)] = self.evaluate('<li><template><template>Grade 10</template>'
            'History textbook</template><script>Grade 12 Chemistry</script>'
            '<a href="/opaque">Download</a></li>')
        self.assertIsNone(candidate)

    def test_unclosed_anchor_cannot_capture_following_resource_text(self):
        page, [(candidate, _)] = self.evaluate('<li><a href="/opaque">Download</li>'
                                              '<p>Grade 10 History textbook</p>')
        self.assertEqual(page.links[0].text, "Download")
        self.assertIsNone(candidate)

    def test_generic_scope_preserves_descriptive_filename_fallback(self):
        _, [(candidate, _)] = self.evaluate('<li><a href="/grade-10-history-textbook.pdf">Download</a></li>')
        self.assertEqual(candidate["title"], "grade 10 history textbook")
        self.assertEqual((candidate["subject"], candidate["grade"]), ("History", "10"))

    def test_pathological_nesting_disables_context_but_keeps_explicit_files(self):
        page, decisions = self.evaluate('<div>' * 140 + '<li>Grade 10 History textbook '
            '<a href="/opaque">Download</a><a href="/history.pdf">History textbook</a></li>' + '</div>' * 140)
        self.assertTrue(all(not link.resource_context for link in page.links))
        self.assertIsNone(decisions[0][0])
        self.assertIsNotNone(decisions[1][0])

    def test_direct_pdf_in_category_path_is_preserved(self):
        _, [(candidate, _)] = self.evaluate('<li>Grade 10 History textbook '
            '<a href="/category/history.pdf">Download</a></li>')
        self.assertIsNotNone(candidate)


if __name__ == "__main__":
    unittest.main()
