import unittest

from src.github_morning_brief import (
    TrendingParser,
    anthropic_headers,
    chunk_text,
    default_headers,
    extract_response_text,
    format_signal,
    infer_area,
    normalize_base_url,
    normalize_text,
    RepoSignal,
)


class GithubMorningBriefTest(unittest.TestCase):
    def test_normalize_text_collapses_whitespace_and_entities(self):
        self.assertEqual(normalize_text("  hello&nbsp;\n world  "), "hello world")

    def test_extract_response_text_supports_responses_output_shape(self):
        payload = {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "hello"},
                        {"type": "output_text", "text": "world"},
                    ]
                }
            ]
        }
        self.assertEqual(extract_response_text(payload), "hello\nworld")

    def test_extract_response_text_supports_anthropic_content_shape(self):
        payload = {"content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]}
        self.assertEqual(extract_response_text(payload), "hello\nworld")

    def test_extract_response_text_supports_openai_chat_shape(self):
        payload = {"choices": [{"message": {"content": "hello"}}]}
        self.assertEqual(extract_response_text(payload), "hello")

    def test_normalize_base_url_strips_markdown_and_trailing_slash(self):
        self.assertEqual(normalize_base_url("[https://example.com](https://example.com/)"), "https://example.com")

    def test_default_headers_do_not_attach_github_token(self):
        headers = default_headers()
        self.assertNotIn("Authorization", headers)

    def test_anthropic_headers_tries_auth_token_and_api_key_styles(self):
        headers = anthropic_headers(auth_token="secret", api_key="")
        self.assertEqual(headers[0]["Authorization"], "Bearer secret")
        self.assertEqual(headers[1]["x-api-key"], "secret")

    def test_format_signal_localizes_common_signals(self):
        signal = "GitHub Trending daily; 12 stars today"
        self.assertEqual(format_signal(signal), "GitHub 今日趋势; 12 今日新增星标")

    def test_infer_area_detects_computational_history(self):
        signal = RepoSignal(
            full_name="owner/history-sim",
            html_url="https://github.com/owner/history-sim",
            description="historical event simulation",
            language="Python",
            stars=1,
            forks=0,
            updated_at="",
            topics=(),
            signal="GitHub search: cliodynamics",
        )
        self.assertEqual(infer_area(signal), "历史预测/计算历史")

    def test_chunk_text_keeps_short_text_as_one_chunk(self):
        self.assertEqual(chunk_text("hello", limit=10), ["hello"])

    def test_chunk_text_splits_long_text(self):
        chunks = chunk_text("a" * 25, limit=10)
        self.assertEqual(chunks, ["a" * 10, "a" * 10, "a" * 5])

    def test_trending_parser_extracts_basic_repo_fields(self):
        parser = TrendingParser()
        parser.feed(
            """
            <article class="Box-row">
              <h2><a href="/owner/repo">owner / repo</a></h2>
              <p class="col-9 color-fg-muted my-1 pr-4">A useful thing</p>
              <span itemprop="programmingLanguage">Python</span>
              <span class="d-inline-block float-sm-right">123 stars today</span>
            </article>
            """
        )
        self.assertEqual(parser.repos[0]["full_name"], "owner/repo")
        self.assertEqual(parser.repos[0]["html_url"], "https://github.com/owner/repo")
        self.assertEqual(parser.repos[0]["description"], "A useful thing")
        self.assertEqual(parser.repos[0]["language"], "Python")


if __name__ == "__main__":
    unittest.main()
