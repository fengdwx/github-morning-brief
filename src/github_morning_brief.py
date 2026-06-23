#!/usr/bin/env python3
"""Build a GitHub morning brief and send it to Feishu."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import http.client
import json
import os
import re
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


DEFAULT_MODEL = "cc-deepseek-v4-pro"
GITHUB_API = "https://api.github.com"
TRENDING_URL = "https://github.com/trending"
MAX_FEISHU_TEXT = 3500

INTEREST_AREAS = [
    "AI/LLM",
    "Agent",
    "developer tools",
    "automation",
    "productivity",
    "open-source infrastructure",
    "engineering practice",
    "product design",
    "cliodynamics",
    "computational history",
    "quantitative history",
    "structural-demographic theory",
    "geopolitical forecasting",
    "prediction markets",
    "temporal reasoning",
    "historical event simulation",
]

SEARCH_QUERIES = [
    "topic:llm stars:>100 pushed:>{date}",
    "topic:ai-agent stars:>50 pushed:>{date}",
    "agentic stars:>50 pushed:>{date}",
    "developer-tools stars:>100 pushed:>{date}",
    "automation stars:>100 pushed:>{date}",
    "productivity stars:>100 pushed:>{date}",
    "infrastructure stars:>100 pushed:>{date}",
    "temporal-reasoning stars:>20 pushed:>{date}",
    "forecasting llm stars:>20 pushed:>{date}",
    "cliodynamics stars:>1 pushed:>{wide_date}",
    "computational-history stars:>1 pushed:>{wide_date}",
    "prediction-markets stars:>5 pushed:>{wide_date}",
    "historical event simulation stars:>1 pushed:>{wide_date}",
]


@dataclass(frozen=True)
class RepoSignal:
    full_name: str
    html_url: str
    description: str
    language: str
    stars: int | None
    forks: int | None
    updated_at: str
    topics: tuple[str, ...]
    signal: str


class TrendingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.repos: list[dict[str, Any]] = []
        self._in_article = False
        self._current: dict[str, Any] | None = None
        self._capture_name = False
        self._capture_desc = False
        self._capture_lang = False
        self._capture_stars_today = False
        self._name_chunks: list[str] = []
        self._desc_chunks: list[str] = []
        self._lang_chunks: list[str] = []
        self._stars_today_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        class_name = attr.get("class", "")
        if tag == "article" and "Box-row" in class_name:
            self._in_article = True
            self._current = {}
            return

        if not self._in_article:
            return

        if tag == "h2":
            self._capture_name = True
            self._name_chunks = []
        elif tag == "p" and "col-9" in class_name:
            self._capture_desc = True
            self._desc_chunks = []
        elif tag == "span" and attr.get("itemprop") == "programmingLanguage":
            self._capture_lang = True
            self._lang_chunks = []
        elif tag == "span" and "d-inline-block float-sm-right" in class_name:
            self._capture_stars_today = True
            self._stars_today_chunks = []
        elif tag == "a" and self._capture_name and self._current is not None:
            href = attr.get("href", "")
            if href.count("/") == 2 and not self._current.get("html_url"):
                self._current["html_url"] = f"https://github.com{href}"

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._capture_name:
            self._capture_name = False
            name = normalize_text("".join(self._name_chunks)).replace(" / ", "/")
            if self._current is not None:
                self._current["full_name"] = name
            return

        if tag == "p" and self._capture_desc:
            self._capture_desc = False
            if self._current is not None:
                self._current["description"] = normalize_text("".join(self._desc_chunks))
            return

        if tag == "span" and self._capture_lang:
            self._capture_lang = False
            if self._current is not None:
                self._current["language"] = normalize_text("".join(self._lang_chunks))
            return

        if tag == "span" and self._capture_stars_today:
            self._capture_stars_today = False
            if self._current is not None:
                self._current["stars_today"] = normalize_text("".join(self._stars_today_chunks))
            return

        if tag == "article" and self._in_article:
            if self._current and self._current.get("full_name"):
                self.repos.append(self._current)
            self._in_article = False
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._capture_name:
            self._name_chunks.append(data)
        elif self._capture_desc:
            self._desc_chunks.append(data)
        elif self._capture_lang:
            self._lang_chunks.append(data)
        elif self._capture_stars_today:
            self._stars_today_chunks.append(data)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    return json.loads(http_bytes(url, headers=headers, timeout=timeout).decode("utf-8"))


def http_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    return http_bytes(url, headers=headers, timeout=timeout).decode("utf-8", errors="replace")


def http_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 30, attempts: int = 3) -> bytes:
    last_error: BaseException | None = None
    merged_headers = default_headers({"Accept-Encoding": "identity", **(headers or {})})
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers=merged_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, http.client.IncompleteRead) and exc.partial and attempt == attempts:
                return bytes(exc.partial)
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(0.8 * attempt)
    assert last_error is not None
    raise last_error


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=default_headers({"Content-Type": "application/json", **(headers or {})}),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw else {}


def default_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": "github-morning-brief/1.0",
    }
    if extra:
        headers.update(extra)
    return headers


def github_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = default_headers({"Accept": "application/vnd.github+json"})
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra:
        headers.update(extra)
    return headers


def fetch_trending(limit: int) -> list[RepoSignal]:
    url = f"{TRENDING_URL}?since=daily"
    try:
        parser = TrendingParser()
        parser.feed(http_text(url, headers={"Accept": "text/html"}))
    except urllib.error.URLError as exc:
        print(f"warning: failed to fetch GitHub Trending: {exc}", file=sys.stderr)
        return []

    signals: list[RepoSignal] = []
    for item in parser.repos[:limit]:
        full_name = str(item.get("full_name", "")).strip()
        if not full_name:
            continue
        signal = "GitHub Trending daily"
        stars_today = str(item.get("stars_today", "")).strip()
        if stars_today:
            signal = f"{signal}; {stars_today}"
        signals.append(
            RepoSignal(
                full_name=full_name,
                html_url=str(item.get("html_url") or f"https://github.com/{full_name}"),
                description=str(item.get("description") or ""),
                language=str(item.get("language") or ""),
                stars=None,
                forks=None,
                updated_at="",
                topics=(),
                signal=signal,
            )
        )
    return signals


def search_repositories(per_query: int) -> list[RepoSignal]:
    today = dt.date.today()
    recent = today - dt.timedelta(days=14)
    wide = today - dt.timedelta(days=365)
    signals: list[RepoSignal] = []

    for template in SEARCH_QUERIES:
        query = template.format(date=recent.isoformat(), wide_date=wide.isoformat())
        params = urllib.parse.urlencode(
            {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": str(per_query),
            }
        )
        url = f"{GITHUB_API}/search/repositories?{params}"
        try:
            payload = http_json(url, headers=github_headers())
        except urllib.error.HTTPError as exc:
            print(f"warning: GitHub search failed for {query!r}: {exc}", file=sys.stderr)
            continue
        except urllib.error.URLError as exc:
            print(f"warning: GitHub search failed for {query!r}: {exc}", file=sys.stderr)
            continue

        for item in payload.get("items", []):
            signals.append(
                RepoSignal(
                    full_name=str(item.get("full_name") or ""),
                    html_url=str(item.get("html_url") or ""),
                    description=str(item.get("description") or ""),
                    language=str(item.get("language") or ""),
                    stars=int(item.get("stargazers_count") or 0),
                    forks=int(item.get("forks_count") or 0),
                    updated_at=str(item.get("updated_at") or ""),
                    topics=tuple(str(topic) for topic in item.get("topics", []) or []),
                    signal=f"GitHub search: {query}",
                )
            )
        time.sleep(0.5)
    return signals


def rank_signals(signals: list[RepoSignal], limit: int) -> list[RepoSignal]:
    seen: set[str] = set()
    unique: list[RepoSignal] = []
    for signal in signals:
        if not signal.full_name or signal.full_name in seen:
            continue
        seen.add(signal.full_name)
        unique.append(signal)

    def score(signal: RepoSignal) -> tuple[int, int]:
        text = " ".join(
            [
                signal.full_name,
                signal.description,
                signal.language,
                " ".join(signal.topics),
                signal.signal,
            ]
        ).lower()
        interest_score = sum(1 for keyword in INTEREST_AREAS if keyword.lower() in text)
        history_bonus = 4 if any(
            keyword in text
            for keyword in [
                "cliodynamics",
                "computational history",
                "prediction market",
                "temporal reasoning",
                "geopolitical forecasting",
                "historical",
            ]
        ) else 0
        trending_bonus = 5 if "trending" in signal.signal.lower() else 0
        star_score = min(signal.stars or 0, 100000)
        return (interest_score * 10 + history_bonus + trending_bonus, star_score)

    return sorted(unique, key=score, reverse=True)[:limit]


def build_source_digest(signals: list[RepoSignal]) -> str:
    lines = []
    for index, signal in enumerate(signals, start=1):
        topics = ", ".join(signal.topics[:8]) if signal.topics else ""
        stars = f"{signal.stars:,}" if signal.stars is not None else "unknown"
        forks = f"{signal.forks:,}" if signal.forks is not None else "unknown"
        lines.append(
            textwrap.dedent(
                f"""\
                {index}. {signal.full_name}
                   URL: {signal.html_url}
                   Description: {signal.description or "No description"}
                   Language: {signal.language or "unknown"}
                   Stars/Forks: {stars}/{forks}
                   Updated: {signal.updated_at or "unknown"}
                   Topics: {topics or "none"}
                   Signal: {signal.signal}
                """
            )
        )
    return "\n".join(lines).strip()


def build_generation_prompt(signals: list[RepoSignal]) -> str:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    source_digest = build_source_digest(signals)
    return f"""
今天是 {today}。请基于下面的 GitHub 项目信号，生成一份中文晨间开源雷达。

要求：
- 筛选 5-8 个项目，不要泛泛而谈。
- 每个项目包含：项目名和链接、领域、趋势信号、一句话介绍、为什么值得关注、适合我的可能用途。
- 每个项目额外给出简短判断：成熟度（玩具项目/可试用/生产可用/需观察）、适合人群、优先级（高/中/低）、风险或噪音、今天最值得点开的文件/页面。
- “为什么值得关注”和“适合我的可能用途”要结合我的兴趣做判断，不要只复述 README。
- 除项目名、链接、代码库名、模型名、编程语言名和必要专有名词外，所有自然语言都必须使用中文；不要直接复制英文 description，请翻译、归纳或解释成中文。
- 优先关注 AI/LLM、Agent、开发者工具、自动化、生产力、开源基础设施、工程实践、产品设计。
- 固定观察一条冷门方向：历史预测/计算历史/社会复杂系统/事件预测，包括 cliodynamics、computational history、quantitative history、structural-demographic theory、geopolitical forecasting、prediction markets、temporal reasoning、历史数据库和历史事件模拟。这个方向不需要硬凑，但发现相关项目要单独提示。
- 末尾给 1-3 条“今天可以深入看”的推荐，并给出明确行动建议，例如先看 README、examples、docs、demo、release、issues 或核心源码入口。
- 输出适合直接发到飞书群，信息密度高，控制在 3600 中文字以内。

项目信号：
{source_digest}
""".strip()


def generate_with_anthropic(signals: list[RepoSignal], model: str) -> str | None:
    auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    base_url = normalize_base_url(os.getenv("ANTHROPIC_BASE_URL", ""))
    if not (auth_token or api_key) or not base_url:
        return None

    payload = {
        "model": model,
        "max_tokens": 3500,
        "system": "你是一个给工程师和产品型创业者写晨间开源情报的研究助理。",
        "messages": [{"role": "user", "content": build_generation_prompt(signals)}],
    }

    response = None
    last_error: BaseException | None = None
    for headers in anthropic_headers(auth_token=auth_token, api_key=api_key):
        try:
            response = post_json(
                f"{base_url}/v1/messages",
                payload,
                headers=headers,
                timeout=120,
            )
            break
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            continue

    if response is None:
        print(f"warning: Anthropic-compatible generation failed: {last_error}", file=sys.stderr)
        return None

    text = extract_response_text(response)
    return text.strip() if text else None


def anthropic_headers(auth_token: str, api_key: str) -> list[dict[str, str]]:
    base = {
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    candidates: list[dict[str, str]] = []
    if auth_token:
        candidates.append({**base, "Authorization": f"Bearer {auth_token}"})
        candidates.append({**base, "x-api-key": auth_token})
    if api_key and api_key != auth_token:
        candidates.append({**base, "x-api-key": api_key})
    return candidates


def normalize_base_url(value: str) -> str:
    text = value.strip()
    markdown_match = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", text)
    if markdown_match:
        text = markdown_match.group(1)
    return text.rstrip("/")


def generate_with_openai(signals: list[RepoSignal], model: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": "你是一个给工程师和产品型创业者写晨间开源情报的研究助理。",
            },
            {"role": "user", "content": build_generation_prompt(signals)},
        ],
    }
    try:
        response = post_json(
            "https://api.openai.com/v1/responses",
            payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=90,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"warning: OpenAI generation failed: {exc}", file=sys.stderr)
        return None

    text = extract_response_text(response)
    return text.strip() if text else None


def extract_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]

    content = response.get("content")
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
        )

    choices = response.get("choices")
    if isinstance(choices, list):
        chunks: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                chunks.append(message["content"])
        if chunks:
            return "\n".join(chunks)

    chunks: list[str] = []
    for item in response.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def build_fallback_brief(signals: list[RepoSignal]) -> str:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    lines = [f"GitHub 晨间简报｜{today}", ""]
    for index, signal in enumerate(signals[:8], start=1):
        stars = f"｜{signal.stars:,} 星标" if signal.stars is not None else ""
        language = f"｜{signal.language}" if signal.language else ""
        area = infer_area(signal)
        lines.extend(
            [
                f"{index}. {signal.full_name}",
                signal.html_url,
                f"领域：{area}",
                f"信号：{format_signal(signal.signal)}{stars}{language}",
                f"简介：这是一个偏 {area} 的项目，今天被算法筛到候选列表；建议点进仓库看 README、示例和最近提交质量。",
                "成熟度：需观察",
                "优先级：中",
                "风险/噪音：未经过模型深度分析，可能只是搜索或趋势信号命中。",
                "今天先看：README、examples/docs、最近 release 和 issue 活跃度。",
                f"可能用途：{suggest_use(area)}",
                "",
            ]
        )
    history_hits = [
        signal
        for signal in signals
        if re.search(r"cliodynamics|history|historical|forecast|prediction|temporal", " ".join([signal.full_name, signal.description, signal.signal]).lower())
    ]
    if history_hits:
        lines.append("冷门观察：历史预测/计算历史方向今天有可看项目，优先看上面相关条目。")
    lines.append("今天可以深入看：优先选择 Trending 且与你当前 AI/Agent/开发者工具兴趣重叠的项目。")
    return "\n".join(lines).strip()


def infer_area(signal: RepoSignal) -> str:
    text = " ".join([signal.full_name, signal.description, signal.language, signal.signal, " ".join(signal.topics)]).lower()
    if any(keyword in text for keyword in ["cliodynamics", "history", "historical", "geopolitical", "prediction market", "temporal"]):
        return "历史预测/计算历史"
    if any(keyword in text for keyword in ["agent", "agents", "agentic"]):
        return "AI Agent"
    if any(keyword in text for keyword in ["llm", "model", "prompt", "rag"]):
        return "AI/LLM"
    if any(keyword in text for keyword in ["video", "render", "media"]):
        return "生成式媒体工具"
    if any(keyword in text for keyword in ["dev", "developer", "cli", "tool", "sdk"]):
        return "开发者工具"
    if any(keyword in text for keyword in ["automation", "workflow", "productivity"]):
        return "自动化/生产力"
    if any(keyword in text for keyword in ["infra", "database", "runtime", "server"]):
        return "开源基础设施"
    return "开源工具"


def suggest_use(area: str) -> str:
    suggestions = {
        "历史预测/计算历史": "作为冷门观察方向，看看它的数据结构、模型假设和 benchmark 是否能迁移到事件预测或研究型 agent。",
        "AI Agent": "观察它如何组织工具、记忆、任务流和评估方式，适合给自己的 agent 工作流找设计参考。",
        "AI/LLM": "重点看模型调用、评估数据和工程封装，判断能否变成自己的开发辅助组件。",
        "生成式媒体工具": "适合观察 agent 如何串联多步骤内容生产，也可以作为自动化素材生成流程的参考。",
        "开发者工具": "可以看 CLI/API 设计、插件机制和本地工作流集成，判断是否能提高日常开发效率。",
        "自动化/生产力": "适合拆解它的触发器、任务编排和通知方式，看看能否接入自己的日常自动化。",
        "开源基础设施": "优先看部署复杂度、稳定性、协议边界和社区活跃度，判断是否值得长期关注。",
    }
    return suggestions.get(area, "先看 README、示例和最近 issue，判断它是不是短期热度还是有真实工程价值。")


def format_signal(signal: str) -> str:
    if signal.startswith("GitHub Trending daily"):
        return signal.replace("GitHub Trending daily", "GitHub 今日趋势").replace("stars today", "今日新增星标")
    if signal.startswith("GitHub search:"):
        query = signal.removeprefix("GitHub search:").strip()
        return f"GitHub 搜索命中：{format_query(query)}"
    return signal


def format_query(query: str) -> str:
    translations = [
        ("topic:llm", "LLM 主题"),
        ("topic:ai-agent", "AI Agent 主题"),
        ("agentic", "Agentic 关键词"),
        ("developer-tools", "开发者工具"),
        ("automation", "自动化"),
        ("productivity", "生产力工具"),
        ("infrastructure", "基础设施"),
        ("temporal-reasoning", "时间推理"),
        ("forecasting llm", "LLM 预测"),
        ("cliodynamics", "历史动力学"),
        ("computational-history", "计算历史"),
        ("prediction-markets", "预测市场"),
        ("historical event simulation", "历史事件模拟"),
        ("stars:>", "星标数大于 "),
        ("pushed:>", "近期更新晚于 "),
    ]
    result = query
    for source, target in translations:
        result = result.replace(source, target)
    return result


def chunk_text(text: str, limit: int = MAX_FEISHU_TEXT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in re.split(r"(\n\s*\n)", text):
        if current_len + len(paragraph) > limit and current:
            chunks.append("".join(current).strip())
            current = []
            current_len = 0
        if len(paragraph) > limit:
            for start in range(0, len(paragraph), limit):
                piece = paragraph[start : start + limit]
                if current:
                    chunks.append("".join(current).strip())
                    current = []
                    current_len = 0
                chunks.append(piece.strip())
        else:
            current.append(paragraph)
            current_len += len(paragraph)
    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def send_to_feishu(text: str, webhook_url: str) -> None:
    chunks = chunk_text(text)
    for index, chunk in enumerate(chunks, start=1):
        prefix = f"[{index}/{len(chunks)}]\n" if len(chunks) > 1 else ""
        payload = {"msg_type": "text", "content": {"text": f"{prefix}{chunk}"}}
        response = post_json(webhook_url, payload, headers={"Accept": "application/json"})
        code = response.get("code", response.get("StatusCode", 0))
        if code not in (0, "0", None):
            raise RuntimeError(f"Feishu webhook returned error: {response}")


def build_brief(limit: int, per_query: int, model: str) -> str:
    signals = rank_signals(fetch_trending(limit=15) + search_repositories(per_query=per_query), limit=limit)
    if not signals:
        raise RuntimeError("No GitHub signals collected.")
    return generate_with_anthropic(signals, model=model) or generate_with_openai(signals, model=model) or build_fallback_brief(signals)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a GitHub morning brief and send it to Feishu.")
    parser.add_argument("--limit", type=int, default=int(os.getenv("BRIEF_REPO_LIMIT", "8")))
    parser.add_argument("--per-query", type=int, default=int(os.getenv("GITHUB_SEARCH_PER_QUERY", "3")))
    parser.add_argument("--model", default=os.getenv("ANTHROPIC_MODEL") or os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--dry-run", action="store_true", help="Print the brief instead of sending it.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    brief = build_brief(limit=args.limit, per_query=args.per_query, model=args.model)
    if args.dry_run:
        print(brief)
        return 0

    webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise RuntimeError("Missing FEISHU_WEBHOOK_URL.")
    send_to_feishu(brief, webhook_url)
    print("Feishu morning brief sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
